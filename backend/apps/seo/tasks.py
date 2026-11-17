from apps.observability.tasks_base import TracedTask
from config.celery import app

from .services import execute_audit


@app.task(base=TracedTask, name="seo.run_audit", module="seo", autoretry_for=(), max_retries=0)
def run_audit(audit_id: str):
    return execute_audit(audit_id)
