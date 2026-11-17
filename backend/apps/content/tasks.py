from apps.observability.tasks_base import TracedTask
from config.celery import app

from . import services as s


@app.task(base=TracedTask, name="content.generate", module="content", max_retries=0, autoretry_for=())
def generate_task(content_id: str, operation: str = "generate", brief: str = "", target_language: str | None = None):
    return s.generate(content_id, operation, brief, target_language)
