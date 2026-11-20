"""Multi-Scheduler + Workflow Engine. State lives in PostgreSQL (runs, steps, locks, approvals) — Celery only
transports work, so every execution is recoverable after a worker restart."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.permissions.growth import effective_mode, register, request_approval

logger = logging.getLogger("growth.workflows")

CATEGORY_MODULE = {"seo": "seo", "geo": "geo", "articles": "content", "pages": "pages", "social": "social", "videos": "video",
                   "opportunities": "opportunities", "social_monitoring": "social_hunter", "prospects": "prospects", "crm": "crm",
                   "reporting": "reporting", "intelligence": "intelligence", "agents": "thor"}


def next_run(freq: str, value: str | None, tz: str, after: datetime | None = None) -> datetime | None:
    zone = ZoneInfo(tz or "UTC")
    now = (after or timezone.now()).astimezone(zone)
    v = (value or "").strip()
    if freq == "hourly":
        n = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    elif freq == "every_x_hours":
        n = now.replace(second=0, microsecond=0) + timedelta(hours=max(1, int(v or 1)))
    elif freq in ("daily", "weekly", "monthly"):
        parts = v.split()
        hh, mm = (parts[-1] if parts else "08:00").split(":")
        n = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if freq == "daily":
            n = n if n > now else n + timedelta(days=1)
        elif freq == "weekly":
            wd = int(parts[0]) if len(parts) > 1 else 0  # 0 = Monday
            n = n + timedelta(days=(wd - n.weekday()) % 7)
            n = n if n > now else n + timedelta(days=7)
        else:
            day = int(parts[0]) if len(parts) > 1 else 1
            n = n.replace(day=min(day, 28))
            if n <= now:
                n = (n.replace(day=1) + timedelta(days=32)).replace(day=min(day, 28))
    elif freq == "cron":
        if not croniter.is_valid(v):
            raise BusinessError("Invalid cron expression", "invalid_cron")
        n = croniter(v, now).get_next(datetime)
    elif freq == "conditional":
        n = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)  # condition evaluated hourly
    else:  # event
        return None
    return n.astimezone(ZoneInfo("UTC"))


# ─────────────────────────── Handlers (shared by schedulers and workflow nodes) ───────────────────────────
def _h_seo(p):
    if p.get("visibility_profile_id"):  # intelligent programme: weekly re-audit, plan re-prioritised from new observations
        from apps.visibility.services import execute_audit as visibility_audit
        from apps.visibility.services import launch_audit as visibility_launch
        vid = visibility_launch(p["visibility_profile_id"], p.get("scope") or ["seo", "geo"])
        if fetch_one("SELECT status FROM public.visibility_audits WHERE id = %s", [vid])[0] == "queued":
            return visibility_audit(vid) | {"visibility_audit_id": vid}
        return {"visibility_audit_id": vid}
    from apps.seo.services import execute_audit, launch_audit
    aid = launch_audit(p["project_id"], p.get("audit_type", "full"), p.get("pages_limit"))
    if fetch_one("SELECT status FROM public.seo_audits WHERE id = %s", [aid])[0] == "queued":
        return execute_audit(aid) | {"audit_id": aid}
    return {"audit_id": aid}


def _h_geo(p):
    from apps.geo.services import run_query, snapshot
    qs = fetch_all_dict("SELECT id FROM public.ai_search_queries WHERE product_id = %s AND is_active AND deleted_at IS NULL", [p["product_id"]])
    out = {str(q["id"]): run_query(str(q["id"])) for q in qs}
    return {"queries": len(out), "visibility": snapshot(p["product_id"])}


def _h_articles(p):
    from apps.content.services import generate
    cid = p.get("content_id")
    if not cid:
        cid = str(fetch_one("""INSERT INTO public.generated_contents (tenant_id, project_id, title, content_type, keyword, objective, product_id, language, status)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'draft') RETURNING id""",
                            [get_context().tenant_id, p["content_project_id"], p.get("title") or p.get("keyword", "Article"), p.get("content_type", "article"),
                             p.get("keyword"), p.get("objective"), p.get("product_id"), p.get("language", "fr")])[0])
    return generate(cid, p.get("operation", "generate"), p.get("brief", "")) | {"content_id": cid}


def _h_pages(p):
    from apps.content.services import request_page_publication
    return request_page_publication(p["page_id"])


def _h_social(p):
    from apps.social.services import request_publish
    due = fetch_all_dict("""SELECT id FROM public.social_publications WHERE tenant_id = %s AND status = 'scheduled' AND scheduled_at <= now()
                             AND deleted_at IS NULL LIMIT 50""", [get_context().tenant_id])
    res = {}
    for d in due:
        try:
            res[str(d["id"])] = request_publish(str(d["id"]))
        except BusinessError as e:
            res[str(d["id"])] = {"error": e.message}
    return {"processed": len(res), "results": res}


def _h_videos(p):
    from apps.social.services import generate_script
    return {"script_id": generate_script(p["project_id"], p.get("brief", ""))}


def _h_opportunities(p):
    from apps.opportunities.services import hunt
    return hunt(p["project_id"])


def _h_social_monitoring(p):
    from apps.opportunities.services import listen
    return listen(p["config_id"])


def _h_prospects(p):
    from apps.prospects.services import process_campaign
    return process_campaign(p["campaign_id"])


def _h_crm(p):
    days = int(p.get("days", 7))
    tid = get_context().tenant_id
    stale = fetch_all_dict("""SELECT id, owner_user_id FROM public.prospects WHERE tenant_id = %s AND deleted_at IS NULL
                               AND status IN ('contacted','interested','demo_requested','proposal_sent','negotiation')
                               AND coalesce(last_activity_at, created_at) < now() - make_interval(days => %s)
                               AND NOT EXISTS (SELECT 1 FROM public.crm_tasks t WHERE t.title LIKE '%%' || prospects.id::text || '%%' AND t.status = 'todo')""",
                           [tid, days])
    for s in stale:
        fetch_one("INSERT INTO public.crm_tasks (tenant_id, title, assigned_to, due_at) VALUES (%s,%s,%s, now() + interval '1 day') RETURNING id",
                  [tid, f"Relancer le prospect {s['id']} (inactif depuis {days} j)", s["owner_user_id"]])
    return {"follow_up_tasks": len(stale)}


def _h_reporting(p):
    from apps.reporting.global_report import build_export
    return {k: v for k, v in build_export(p.get("format", "pdf"), p.get("days", 30)).items() if not k.startswith("_")}


def _h_intelligence(p):
    from apps.intelligence.engine import run_cycle
    return run_cycle()


def _h_agents(p):
    from apps.thor.engine import chat
    return chat(None, p["prompt"], product_id=p.get("product_id"), read_only=True)


HANDLERS = {"seo": _h_seo, "geo": _h_geo, "articles": _h_articles, "pages": _h_pages, "social": _h_social, "videos": _h_videos,
            "opportunities": _h_opportunities, "social_monitoring": _h_social_monitoring, "prospects": _h_prospects, "crm": _h_crm,
            "reporting": _h_reporting, "intelligence": _h_intelligence, "agents": _h_agents}
# actions with side effects outside Growth IA go through the growth gate
GATED = {"pages": ("pages", "publish"), "social": ("social", "publish"), "prospects": ("prospects", "send_campaign")}


def _condition_met(cond: dict) -> bool:
    metric = {"seo_score": "SELECT score FROM public.seo_audits WHERE tenant_id = %s AND status = 'succeeded' ORDER BY completed_at DESC LIMIT 1",
              "new_signals_24h": "SELECT count(*) FROM public.social_signals WHERE tenant_id = %s AND created_at > now() - interval '24 hours'",
              "unread_emails": "SELECT count(*) FROM public.email_conversations WHERE tenant_id = %s AND is_unread"}.get(cond.get("metric"))
    if not metric:
        return False
    v = fetch_one(metric, [get_context().tenant_id])
    v = float(v[0]) if v and v[0] is not None else None
    if v is None:
        return False
    t = float(cond.get("threshold", 0))
    return {"lt": v < t, "lte": v <= t, "gt": v > t, "gte": v >= t, "eq": v == t}.get(cond.get("op", "gt"), False)


# ─────────────────────────── Scheduler runs ───────────────────────────
def enqueue_run(scheduler_id: str, triggered_by: str = "schedule") -> str | None:
    ctx = get_context()
    s = fetch_one("SELECT tenant_id, frequency_type, frequency_value, timezone, status, params FROM public.tenant_schedulers WHERE id = %s", [scheduler_id])
    if not s or s[4] != "active":
        return None
    if s[1] == "conditional" and triggered_by == "schedule" and not _condition_met((s[5] or {}).get("condition", {})):
        fetch_one("UPDATE public.tenant_schedulers SET next_run_at = %s WHERE id = %s RETURNING 1", [next_run(s[1], s[2], s[3]), scheduler_id])
        return None
    exec_id = str(uuid.uuid4())
    run = fetch_one("""INSERT INTO public.scheduler_execution_runs (tenant_id, scheduler_id, execution_id, status, triggered_by, correlation_id)
                       VALUES (%s,%s,%s,'queued',%s,%s) RETURNING id""", [str(s[0]), scheduler_id, exec_id, triggered_by, ctx.correlation_id])[0]
    fetch_one("UPDATE public.tenant_schedulers SET next_run_at = %s WHERE id = %s RETURNING 1",
              [next_run(s[1], s[2], s[3]) if s[1] not in ("event",) else None, scheduler_id])
    from .tasks import run_scheduler_task
    transaction.on_commit(lambda: run_scheduler_task.delay_traced(str(run)))
    return str(run)


def _step(run_id: str, name: str, status: str, output: dict | None = None) -> None:
    fetch_one("""INSERT INTO public.scheduler_execution_steps (tenant_id, run_id, step_name, status, started_at, completed_at, output_summary)
                 VALUES (%s,%s,%s,%s, now(), CASE WHEN %s IN ('succeeded','failed','skipped') THEN now() END, %s::jsonb) RETURNING id""",
              [get_context().tenant_id, run_id, name, status, status, json.dumps(output or {}, default=str)])


def execute_run(run_id: str) -> dict:
    tid = get_context().tenant_id
    r = fetch_one("""SELECT r.scheduler_id, s.category, s.params, s.mode, s.budget_cents, s.name, r.status, s.created_by
                       FROM public.scheduler_execution_runs r JOIN public.tenant_schedulers s ON s.id = r.scheduler_id WHERE r.id = %s AND r.tenant_id = %s""", [run_id, tid])
    if not r or r[6] != "queued":
        return {"status": "skipped"}
    sid, cat, params, mode, budget, name, _, creator = r
    lock_key = f"scheduler:{sid}"
    got = fetch_one("""INSERT INTO public.scheduler_resource_locks (tenant_id, resource_key, locked_by, execution_id, expires_at)
                       VALUES (%s,%s,%s,%s, now() + interval '2 hours')
                       ON CONFLICT (tenant_id, resource_key) WHERE deleted_at IS NULL DO UPDATE SET locked_by = EXCLUDED.locked_by, execution_id = EXCLUDED.execution_id,
                         expires_at = EXCLUDED.expires_at WHERE scheduler_resource_locks.expires_at < now() RETURNING id""", [tid, lock_key, run_id, get_context().execution_id])
    if not got:
        fetch_one("UPDATE public.scheduler_execution_runs SET status = 'cancelled', error_message = 'previous execution still running' WHERE id = %s RETURNING 1", [run_id])
        return {"status": "cancelled"}
    started = timezone.now()
    fetch_one("UPDATE public.scheduler_execution_runs SET status = 'running', started_at = now() WHERE id = %s RETURNING 1", [run_id])
    try:
        from apps.core.tenancy import module_enabled
        from apps.licensing.services import ensure_active_subscription
        ensure_active_subscription(tid)
        _step(run_id, "licence_check", "succeeded")
        if not module_enabled(tid, CATEGORY_MODULE[cat]):
            raise BusinessError(f"Module {CATEGORY_MODULE[cat]} not authorized", "module_not_authorized")
        if budget is not None:
            spent = fetch_one("""SELECT coalesce(sum(cost_cents),0) FROM public.scheduler_execution_runs WHERE scheduler_id = %s
                                  AND created_at >= date_trunc('month', now())""", [sid])[0]
            if float(spent) >= float(budget):
                raise BusinessError("Scheduler monthly budget reached", "budget_exceeded")
        _step(run_id, "module_budget_check", "succeeded")
        if mode == "analysis" and cat in GATED:
            result = {"analysis_only": True, "note": "mode analysis: no external action executed"}
        elif mode == "approval" and cat in GATED:
            appr = request_approval(*GATED[cat], entity_type="tenant_schedulers", entity_id=sid, payload={"run_id": run_id, "params": params},
                                    agent=f"scheduler:{name}")
            result = {"pending_approval": appr}
        else:
            result = HANDLERS[cat](params or {})
        _step(run_id, cat, "succeeded", result)
        cost = fetch_one("SELECT sum(cost_cents) FROM public.ai_execution_logs WHERE tenant_id = %s AND created_at >= %s AND user_id IS NOT DISTINCT FROM %s",
                         [tid, started, get_context().user_id])[0]
        fetch_one("""UPDATE public.scheduler_execution_runs SET status = 'succeeded', completed_at = now(), duration_ms = %s, result = %s::jsonb, cost_cents = %s
                      WHERE id = %s RETURNING 1""", [int((timezone.now() - started).total_seconds() * 1000), json.dumps(result, default=str)[:100000], cost, run_id])
        fetch_one("UPDATE public.tenant_schedulers SET last_run_at = now(), last_status = 'succeeded' WHERE id = %s RETURNING 1", [sid])
        return {"status": "succeeded", "result": result}
    except Exception as e:  # noqa: BLE001 — persisted, notified, re-raised
        msg = getattr(e, "message", None) or f"{type(e).__name__}: {e}"
        _step(run_id, cat, "failed", {"error": msg[:1000]})
        fetch_one("""UPDATE public.scheduler_execution_runs SET status = 'failed', completed_at = now(), error_message = %s,
                       duration_ms = %s WHERE id = %s RETURNING 1""", [msg[:2000], int((timezone.now() - started).total_seconds() * 1000), run_id])
        fetch_one("UPDATE public.tenant_schedulers SET last_run_at = now(), last_status = 'failed' WHERE id = %s RETURNING 1", [sid])
        from apps.notifications.service import notify
        notify("scheduler.failed", {"name": name, "error": msg[:200]}, users=[str(creator)] if creator else None, permission="scheduler.read")
        record_audit("scheduler.run_failed", "scheduler", entity_type="scheduler_execution_runs", entity_id=run_id, status="failure", description=msg[:500])
        return {"status": "failed", "error": msg}
    finally:
        fetch_one("UPDATE public.scheduler_resource_locks SET expires_at = now() WHERE tenant_id = %s AND resource_key = %s RETURNING 1", [tid, lock_key])


def fire_event(event: str, tenant_id: str) -> int:
    rows = fetch_all_dict("""SELECT id FROM public.tenant_schedulers WHERE tenant_id = %s AND frequency_type = 'event' AND frequency_value = %s
                              AND status = 'active' AND deleted_at IS NULL""", [tenant_id, event])
    return sum(1 for r in rows if enqueue_run(str(r["id"]), "dependency"))


# ─────────────────────────── Workflow engine ───────────────────────────
NODE_TYPES = {"seo_scan": "seo", "detect_opportunities": "opportunities", "generate_content": "articles", "social_signals": "social_monitoring",
              "qualify_prospects": None, "geo_optimize": None, "approval": None, "publish_content": None, "notify": None, "measure": None,
              "condition": None, "wait": None}
MAX_ATTEMPTS = 3


def validate_definition(d: dict) -> None:
    nodes = {n["key"]: n for n in d.get("nodes", [])}
    if not nodes or d.get("start") not in nodes:
        raise BusinessError("Workflow needs nodes and a valid start node", "invalid_workflow")
    for n in nodes.values():
        if n.get("type") not in NODE_TYPES:
            raise BusinessError(f"Unknown node type {n.get('type')}", "invalid_workflow")
        for k in (n.get("next"), n.get("on_failure"), n.get("on_true"), n.get("on_false")):
            if k and k not in nodes:
                raise BusinessError(f"Node {n['key']} points to unknown node {k}", "invalid_workflow")


def start_workflow(workflow_id: str, inp: dict, triggered_by: str | None) -> str:
    tid = get_context().tenant_id
    d = fetch_one("SELECT definition, status FROM public.growth_workflow_definitions WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL", [workflow_id, tid])
    if not d:
        raise BusinessError("workflow not found", "not_found", status_code=404)
    if d[1] != "active":
        raise BusinessError("Workflow must be active", "invalid_state", status_code=409)
    validate_definition(d[0])
    wex = str(uuid.uuid4())
    eid = fetch_one("""INSERT INTO public.growth_workflow_executions (tenant_id, workflow_id, workflow_execution_id, status, started_at, triggered_by, input, context, current_node)
                       VALUES (%s,%s,%s,'queued', now(), %s, %s::jsonb, %s::jsonb, %s) RETURNING id""",
                    [tid, workflow_id, wex, triggered_by, json.dumps(inp), json.dumps(inp), d[0]["start"]])[0]
    record_audit("workflow.started", "workflows", entity_type="growth_workflow_executions", entity_id=eid, after={"input": inp})
    from .tasks import advance_workflow_task
    transaction.on_commit(lambda: advance_workflow_task.delay_traced(str(eid)))
    return str(eid)


def _run_node(node: dict, ctx: dict, execution_id: str) -> tuple[str, dict]:
    t, p = node["type"], {**node.get("params", {}), **{k: v for k, v in ctx.items() if k in ("product_id", "project_id", "content_id")}}
    if t in ("seo_scan", "detect_opportunities", "generate_content", "social_signals"):
        return "ok", HANDLERS[NODE_TYPES[t]](p)
    if t == "geo_optimize":
        from apps.content.services import generate
        return "ok", generate(p["content_id"], "optimize_geo")
    if t == "qualify_prospects":
        from apps.prospects.services import qualify
        ids = fetch_all_dict("SELECT id FROM public.prospects WHERE tenant_id = %s AND status IN ('new','new_lead') AND deleted_at IS NULL LIMIT 200", [get_context().tenant_id])
        return "ok", {"qualified": [qualify(str(i["id"]))["score"] for i in ids]}
    if t == "publish_content":
        from apps.content.services import request_publication
        return "ok", request_publication(p["content_id"], p["connector_account_id"])
    if t == "notify":
        from apps.notifications.service import notify
        return "ok", {"sent": notify(p.get("event", "report.ready"), {"title": p.get("message", "Workflow")}, permission=p.get("permission", "workflows.read"))}
    if t == "measure":
        from apps.intelligence.engine import observe
        return "ok", observe()
    if t == "condition":
        return ("true" if _condition_met(p) else "false"), {}
    if t == "approval":
        appr = request_approval("workflows", "resume", entity_type="growth_workflow_executions", entity_id=execution_id, payload={"node": node["key"]},
                                agent="workflow")
        return "wait", {"approval_id": appr}
    if t == "wait":
        return "ok", {}
    raise BusinessError(f"node type {t} not executable", "invalid_workflow")


def advance(execution_id: str) -> dict:
    tid = get_context().tenant_id
    with transaction.atomic():
        ex = fetch_one("""SELECT e.status, e.current_node, e.context, e.cancel_requested, d.definition FROM public.growth_workflow_executions e
                           JOIN public.growth_workflow_definitions d ON d.id = e.workflow_id WHERE e.id = %s AND e.tenant_id = %s FOR UPDATE OF e""", [execution_id, tid])
        if not ex or ex[0] in ("succeeded", "failed", "cancelled", "waiting_approval"):
            return {"status": ex[0] if ex else "missing"}
        status, node_key, ctx, cancel, definition = ex
        if cancel:
            fetch_one("UPDATE public.growth_workflow_executions SET status = 'cancelled', completed_at = now() WHERE id = %s RETURNING 1", [execution_id])
            return {"status": "cancelled"}
        fetch_one("UPDATE public.growth_workflow_executions SET status = 'running' WHERE id = %s RETURNING 1", [execution_id])
    nodes = {n["key"]: n for n in definition["nodes"]}
    steps = 0
    while node_key and steps < 50:
        steps += 1
        node = nodes[node_key]
        attempt = (fetch_one("SELECT count(*) FROM public.growth_workflow_execution_steps WHERE execution_id = %s AND node_key = %s", [execution_id, node_key])[0] or 0) + 1
        if fetch_one("SELECT 1 FROM public.growth_workflow_execution_steps WHERE execution_id = %s AND node_key = %s AND status = 'succeeded'", [execution_id, node_key]):
            node_key = node.get("next")  # idempotent resume: never re-run a succeeded step
            continue
        sid = fetch_one("""INSERT INTO public.growth_workflow_execution_steps (tenant_id, execution_id, node_key, status, started_at, attempt, idempotency_key)
                           VALUES (%s,%s,%s,'running', now(), %s, %s) RETURNING id""", [tid, execution_id, node_key, attempt, f"{execution_id}:{node_key}:{attempt}"])[0]
        try:
            outcome, out = _run_node(node, ctx, execution_id)
        except Exception as e:  # noqa: BLE001
            logger.exception("workflow node %s failed", node_key)
            msg = getattr(e, "message", None) or f"{type(e).__name__}: {e}"
            if attempt < node.get("max_attempts", MAX_ATTEMPTS) and not isinstance(e, BusinessError):
                delay = 60 * 2 ** (attempt - 1)
                fetch_one("UPDATE public.growth_workflow_execution_steps SET status = 'retrying', error_message = %s, next_retry_at = now() + make_interval(secs => %s) WHERE id = %s RETURNING 1",
                          [msg[:1000], delay, sid])
                fetch_one("UPDATE public.growth_workflow_executions SET status = 'queued', current_node = %s WHERE id = %s RETURNING 1", [node_key, execution_id])
                from .tasks import advance_workflow_task
                advance_workflow_task.apply_async(args=[execution_id], countdown=delay, headers=get_context().to_headers())
                return {"status": "retrying", "node": node_key}
            fetch_one("UPDATE public.growth_workflow_execution_steps SET status = 'failed', error_message = %s, completed_at = now() WHERE id = %s RETURNING 1", [msg[:1000], sid])
            if node.get("on_failure"):
                node_key = node["on_failure"]
                continue
            fetch_one("UPDATE public.growth_workflow_executions SET status = 'failed', error_message = %s, completed_at = now(), current_node = %s WHERE id = %s RETURNING 1",
                      [msg[:1000], node_key, execution_id])
            return {"status": "failed", "node": node_key, "error": msg}
        if outcome == "wait":
            fetch_one("UPDATE public.growth_workflow_execution_steps SET status = 'waiting_approval', output_summary = %s::jsonb WHERE id = %s RETURNING 1",
                      [json.dumps(out, default=str), sid])
            fetch_one("UPDATE public.growth_workflow_executions SET status = 'waiting_approval', current_node = %s WHERE id = %s RETURNING 1", [node_key, execution_id])
            return {"status": "waiting_approval", "node": node_key}
        ctx = {**ctx, **{k: v for k, v in (out or {}).items() if k in ("content_id", "audit_id", "project_id")}, f"out_{node_key}": out}
        fetch_one("UPDATE public.growth_workflow_execution_steps SET status = 'succeeded', completed_at = now(), output_summary = %s::jsonb WHERE id = %s RETURNING 1",
                  [json.dumps(out, default=str)[:100000], sid])
        node_key = node.get("on_true") if outcome == "true" else node.get("on_false") if outcome == "false" else node.get("next")
        fetch_one("UPDATE public.growth_workflow_executions SET context = %s::jsonb, current_node = %s WHERE id = %s RETURNING 1",
                  [json.dumps(ctx, default=str)[:500000], node_key, execution_id])
    fetch_one("UPDATE public.growth_workflow_executions SET status = 'succeeded', completed_at = now() WHERE id = %s RETURNING 1", [execution_id])
    record_activity("workflow.completed", "workflows", entity_type="growth_workflow_executions", entity_id=execution_id)
    return {"status": "succeeded", "steps": steps}


@register("workflows", "resume")
def resume_after_approval(approval: dict) -> dict:
    eid = approval["entity_id"]
    node = approval["payload"]["node"]
    fetch_one("""UPDATE public.growth_workflow_execution_steps SET status = 'succeeded', completed_at = now()
                  WHERE execution_id = %s AND node_key = %s AND status = 'waiting_approval' RETURNING 1""", [eid, node])
    nxt = next((n.get("next") for n in fetch_one("""SELECT d.definition FROM public.growth_workflow_executions e JOIN public.growth_workflow_definitions d ON d.id = e.workflow_id
                                                     WHERE e.id = %s""", [eid])[0]["nodes"] if n["key"] == node), None)
    fetch_one("UPDATE public.growth_workflow_executions SET status = 'queued', current_node = %s WHERE id = %s RETURNING 1", [nxt, eid])
    if nxt is None:
        fetch_one("UPDATE public.growth_workflow_executions SET status = 'succeeded', completed_at = now() WHERE id = %s RETURNING 1", [eid])
        return {"status": "succeeded"}
    from .tasks import advance_workflow_task
    advance_workflow_task.delay_traced(eid)
    return {"status": "resumed", "next": nxt}


def recover_stale() -> dict:
    """Worker crash recovery: runs stuck in 'running' > 2h are marked failed and re-queued once (platform task)."""
    stale = fetch_all_dict("""UPDATE public.scheduler_execution_runs SET status = 'failed', error_message = 'worker lost (recovered)', completed_at = now()
                               WHERE status IN ('running','queued') AND coalesce(started_at, created_at) < now() - interval '2 hours'
                               RETURNING id, tenant_id, scheduler_id""")
    wf = fetch_all_dict("""SELECT id, tenant_id FROM public.growth_workflow_executions WHERE status IN ('running','queued')
                            AND updated_at < now() - interval '30 minutes'""")
    return {"scheduler_runs_recovered": len(stale), "workflows_to_resume": [(str(w["id"]), str(w["tenant_id"])) for w in wf],
            "scheduler_retry": [(str(s["tenant_id"]), str(s["scheduler_id"])) for s in stale]}

_ = effective_mode
