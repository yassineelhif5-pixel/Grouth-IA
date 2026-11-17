from apps.observability.tasks_base import TracedTask
from config.celery import app

from . import services as s


@app.task(base=TracedTask, name="opportunities.hunt", module="opportunities", max_retries=0, autoretry_for=())
def hunt_task(project_id: str):
    return s.hunt(project_id)


@app.task(base=TracedTask, name="opportunities.listen", module="opportunities", max_retries=0, autoretry_for=())
def listen_task(config_id: str):
    return s.listen(config_id)
