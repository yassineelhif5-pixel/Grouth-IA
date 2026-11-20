"""Celery: separate queues, retries with exponential backoff, dead-letter persistence, idempotency,
context propagation (correlation_id from the HTTP request to the worker) and DB-persisted executions."""
import os

from celery import Celery
from kombu import Queue

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("growth_ia")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.task_queues = (Queue("default"), Queue("health"), Queue("notifications"), Queue("maintenance"),
                        Queue("integrations"), Queue("dead_letter"))
app.conf.task_routes = {
    "system_health.*": {"queue": "health"},
    "notifications.*": {"queue": "notifications"},
    "maintenance.*": {"queue": "maintenance"},
    "licensing.*": {"queue": "maintenance"},
    "integrations.*": {"queue": "integrations"},
    "email.*": {"queue": "integrations"},
}
app.conf.beat_schedule = {
    "health-checks": {"task": "system_health.run_all_checks", "schedule": 300.0},
    "beat-heartbeat": {"task": "system_health.beat_heartbeat", "schedule": 60.0},
    "dispatch-scheduled-notifications": {"task": "notifications.dispatch_scheduled", "schedule": 60.0},
    "expire-trials": {"task": "licensing.expire_trials", "schedule": 600.0},
    "ensure-partitions": {"task": "maintenance.ensure_partitions", "schedule": 86400.0},
    "retention-purge": {"task": "maintenance.purge_retention", "schedule": 86400.0},
    "connector-health": {"task": "integrations.check_connectors", "schedule": 3600.0},
    "scheduler-dispatch": {"task": "scheduler.dispatch", "schedule": 60.0},
    "scheduler-recover": {"task": "scheduler.recover", "schedule": 300.0},
    "email-sync": {"task": "email.sync_all", "schedule": 300.0},
    "campaigns": {"task": "prospects.process_campaigns", "schedule": 300.0},
}
app.autodiscover_tasks(lambda: ["apps.system_health", "apps.notifications", "apps.licensing", "apps.observability", "apps.integrations",
                                "apps.products", "apps.seo", "apps.geo", "apps.content", "apps.opportunities", "apps.prospects",
                                "apps.email_center", "apps.scheduler", "apps.visibility"])
