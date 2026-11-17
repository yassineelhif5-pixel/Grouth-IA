from apps.core.db import fetch_all_dict
from apps.observability.tasks_base import TracedTask, run_in_platform_scope, run_in_tenant_scope
from config.celery import app

from . import services as s


@app.task(base=TracedTask, name="prospects.process_campaigns", module="prospects")
def process_campaigns():
    camps = run_in_platform_scope(lambda: fetch_all_dict("SELECT id, tenant_id FROM public.prospect_campaigns WHERE status = 'running' AND deleted_at IS NULL"))
    out = {}
    for c in camps:
        try:
            out[str(c["id"])] = run_in_tenant_scope(str(c["tenant_id"]), lambda c=c: s.process_campaign(str(c["id"])))
        except Exception as e:  # noqa: BLE001
            out[str(c["id"])] = {"error": str(e)[:200]}
    return out
