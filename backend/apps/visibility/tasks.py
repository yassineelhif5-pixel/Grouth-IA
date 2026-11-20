from apps.observability.tasks_base import TracedTask
from config.celery import app

from .services import execute_audit


@app.task(base=TracedTask, name="visibility.run_audit", module="visibility", autoretry_for=(), max_retries=0)
def run_visibility_audit(audit_id: str):
    return execute_audit(audit_id)
