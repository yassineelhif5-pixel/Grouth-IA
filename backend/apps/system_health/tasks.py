import time

import redis
from django.conf import settings

from apps.observability.tasks_base import TracedTask, run_in_platform_scope
from config.celery import app

from .services import run_checks


@app.task(base=TracedTask, name="system_health.run_all_checks", module="system_health")
def run_all_checks():
    results = run_in_platform_scope(lambda: run_checks())
    return {"checks": len(results), "down": sum(1 for r in results if r["status"] == "down")}


@app.task(base=TracedTask, name="system_health.beat_heartbeat", module="system_health")
def beat_heartbeat():
    redis.Redis.from_url(settings.REDIS_URL).set("growth:heartbeat:beat", str(time.time()), ex=600)
    return {"ok": True}
