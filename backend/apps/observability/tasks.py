from config.celery import app

from apps.core.db import fetch_all_dict, fetch_one
from apps.observability.tasks_base import TracedTask, run_in_platform_scope

PARTITIONED = ("audit_events", "activity_events", "execution_logs", "application_logs")


@app.task(base=TracedTask, name="maintenance.ensure_partitions", module="maintenance")
def ensure_partitions():
    return {"created": run_in_platform_scope(
        lambda: sum(fetch_one("SELECT app.ensure_monthly_partitions(%s, 3)", [t])[0] for t in PARTITIONED))}


@app.task(base=TracedTask, name="maintenance.purge_retention", module="maintenance")
def purge_retention():
    """Purge only categories with an explicit active 'delete' policy (app.purge_expired enforces it)."""
    def _run():
        policies = fetch_all_dict("""SELECT DISTINCT data_category FROM public.data_retention_policies
                                      WHERE is_active AND deletion_rule = 'delete' AND deleted_at IS NULL""")
        return {p["data_category"]: fetch_one("SELECT app.purge_expired(%s, NULL)", [p["data_category"]])[0] for p in policies}
    return run_in_platform_scope(_run)
