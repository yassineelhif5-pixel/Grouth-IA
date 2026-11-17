from config.celery import app

from apps.core.db import fetch_all_dict, fetch_one
from apps.observability.tasks_base import TracedTask, run_in_platform_scope


@app.task(base=TracedTask, name="integrations.check_connectors", module="integrations")
def check_connectors():
    """Records a real health status per connected account. Provider-specific probes are added with each
    connector implementation; until then an account without stored credentials is reported not_configured."""
    def _run():
        accounts = fetch_all_dict("""SELECT a.id, a.tenant_id, a.status,
                                            EXISTS (SELECT 1 FROM public.tenant_connector_credentials c
                                                     WHERE c.account_id = a.id AND c.deleted_at IS NULL) AS has_credentials
                                       FROM public.tenant_connector_accounts a WHERE a.deleted_at IS NULL""")
        for a in accounts:
            status = "unknown" if a["has_credentials"] else "not_configured"
            fetch_one("""INSERT INTO public.connector_health_checks (tenant_id, account_id, status, error_message)
                         VALUES (%s, %s, %s, %s) RETURNING id""",
                      [a["tenant_id"], a["id"], status, None if a["has_credentials"] else "no credentials stored"])
        return {"accounts_checked": len(accounts)}
    return run_in_platform_scope(_run)
