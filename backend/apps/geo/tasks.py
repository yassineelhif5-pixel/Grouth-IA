from apps.observability.tasks_base import TracedTask
from config.celery import app

from .services import geo_audit, run_query, snapshot


@app.task(base=TracedTask, name="geo.run_query", module="geo", max_retries=0, autoretry_for=())
def run_query_task(query_id: str):
    return run_query(query_id)


@app.task(base=TracedTask, name="geo.audit", module="geo", max_retries=0, autoretry_for=())
def geo_audit_task(product_id: str):
    return {"audit_id": geo_audit(product_id)}


@app.task(base=TracedTask, name="geo.snapshot", module="geo")
def snapshot_task(product_id: str):
    return snapshot(product_id)
