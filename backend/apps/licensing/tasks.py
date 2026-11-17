from config.celery import app

from apps.core.db import fetch_one
from apps.observability.tasks_base import TracedTask, run_in_platform_scope


@app.task(base=TracedTask, name="licensing.expire_trials", module="licensing")
def expire_trials():
    return {"expired": run_in_platform_scope(lambda: fetch_one("SELECT app.expire_trials()")[0])}
