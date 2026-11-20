"""Periodic tasks without Celery Beat (Vercel / serverless).

On Vercel there is no long-running Celery Beat nor worker: tasks run eagerly inside the request. This endpoint is
called on a schedule (Vercel Cron or any external cron service, e.g. every 5 minutes) and runs every task of
`app.conf.beat_schedule` that is due — the same schedule Celery Beat uses when a worker is available.

Guarantees
- Authentication: shared secret `CRON_SECRET` (header `Authorization: Bearer <secret>`, the scheme Vercel Cron uses).
  Without a configured secret the endpoint is disabled (503).
- Exactly once per period: each (task, time slot) is claimed in `idempotency_keys` before running, so overlapping
  or repeated calls never run the same occurrence twice.
- No overlap: a PostgreSQL advisory lock serialises ticks; a tick that finds the lock busy returns `busy`.
- Bounded: tasks are not started once the time budget (default 45 s, under Vercel's 60 s limit) is spent; they run
  at the next tick.
- Traceability: every task runs through TracedTask (execution_logs, correlation id); failures are reported in the
  response and in the execution log, never silently dropped.
"""
from __future__ import annotations

import logging
import time

from django.conf import settings
from django.db import transaction
from django.utils.decorators import method_decorator
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .context import get_context, new_id, set_context
from .db import apply_db_context, fetch_one
from .webhooks import claim_once, safe_equals

logger = logging.getLogger("growth.cron")
LOCK_KEY = 74_210_001  # arbitrary, constant advisory-lock key for the cron tick


class CronThrottle(AnonRateThrottle):
    rate = "30/min"


def _platform_scope() -> None:
    ctx = get_context().with_(is_platform=True, actor_type="celery", tenant_id=None)
    set_context(ctx)
    apply_db_context(ctx, session=True)


def due_tasks(schedule: dict, now: float) -> list[tuple[str, str, int]]:
    """(entry name, task name, slot) for every beat entry; slot = index of the current period."""
    out = []
    for name, entry in schedule.items():
        every = entry.get("schedule")
        seconds = every if isinstance(every, (int, float)) else getattr(every, "total_seconds", lambda: None)()
        if not seconds or seconds <= 0:
            continue  # crontab-style entries are not supported here (none in the current schedule)
        out.append((name, entry["task"], int(now // seconds)))
    return out


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class CronTickView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [CronThrottle]

    def get(self, request):  # Vercel Cron issues GET requests
        return self.post(request)

    def post(self, request):
        secret = getattr(settings, "CRON_SECRET", "")
        if not secret:
            return Response({"error": {"code": "cron_disabled", "message": "CRON_SECRET is not configured"}}, status=503)
        given = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if not safe_equals(given, secret):
            return Response({"error": {"code": "forbidden", "message": "Invalid cron secret"}}, status=403)

        from config.celery import app as celery_app  # late import: Django must be ready

        celery_app.loader.import_default_modules()  # registers every app's tasks (autodiscovery) in this web process

        set_context(get_context().with_(correlation_id=new_id()))
        _platform_scope()
        if not fetch_one("SELECT pg_try_advisory_lock(%s)", [LOCK_KEY])[0]:
            return Response({"status": "busy"})
        started, budget = time.monotonic(), float(getattr(settings, "CRON_TIME_BUDGET_SECONDS", 45))
        report: dict[str, str] = {}
        try:
            for name, task_name, slot in due_tasks(celery_app.conf.beat_schedule, time.time()):
                if time.monotonic() - started > budget:
                    report[name] = "deferred"
                    continue
                _platform_scope()
                if not claim_once("cron", f"{task_name}:{slot}", days=2):
                    report[name] = "already_done"
                    continue
                task = celery_app.tasks.get(task_name)
                if task is None:
                    report[name] = "unknown_task"
                    continue
                try:
                    result = task.apply()
                    report[name] = "failed" if result.failed() else "ok"
                    if result.failed():
                        logger.warning("cron task %s failed: %s", task_name, result.result)
                except Exception as exc:  # noqa: BLE001 — one failing task must not stop the others
                    report[name] = "failed"
                    logger.exception("cron task %s crashed: %s", task_name, exc)
        finally:
            _platform_scope()
            fetch_one("SELECT pg_advisory_unlock(%s)", [LOCK_KEY])
        return Response({"status": "ok", "tasks": report, "duration_ms": int((time.monotonic() - started) * 1000)})
