from apps.core.db import fetch_all_dict
from apps.observability.tasks_base import TracedTask, run_in_platform_scope, run_in_tenant_scope
from config.celery import app

from . import engine


@app.task(base=TracedTask, name="scheduler.dispatch", module="scheduler")
def dispatch():
    """Every minute: due schedulers → persisted runs (SKIP LOCKED: safe with several beat/worker instances)."""
    due = run_in_platform_scope(lambda: fetch_all_dict(
        """SELECT id, tenant_id FROM public.tenant_schedulers WHERE status = 'active' AND deleted_at IS NULL AND next_run_at <= now()
           ORDER BY next_run_at LIMIT 200 FOR UPDATE SKIP LOCKED"""))
    started = 0
    for d in due:
        started += bool(run_in_tenant_scope(str(d["tenant_id"]), lambda d=d: engine.enqueue_run(str(d["id"]))))
    return {"due": len(due), "started": started}


@app.task(base=TracedTask, name="scheduler.run", module="scheduler", max_retries=0, autoretry_for=())
def run_scheduler_task(run_id: str):
    return engine.execute_run(run_id)


@app.task(base=TracedTask, name="scheduler.advance_workflow", module="workflows", max_retries=0, autoretry_for=())
def advance_workflow_task(execution_id: str):
    return engine.advance(execution_id)


@app.task(base=TracedTask, name="scheduler.recover", module="scheduler")
def recover():
    res = run_in_platform_scope(engine.recover_stale)
    for tenant, sid in res["scheduler_retry"]:
        run_in_tenant_scope(tenant, lambda sid=sid: engine.enqueue_run(sid, "retry"))
    for eid, tenant in res["workflows_to_resume"]:
        run_in_tenant_scope(tenant, lambda eid=eid: engine.advance(eid))
    return {"recovered_runs": res["scheduler_runs_recovered"], "resumed_workflows": len(res["workflows_to_resume"])}
