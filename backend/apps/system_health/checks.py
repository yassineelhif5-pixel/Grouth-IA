"""Real, non-destructive health checks. A check is Healthy only if the probe actually succeeded.
Statuses: healthy | degraded | down | not_configured | unknown | checking."""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field

import requests
from django.conf import settings
from django.db import connection

REQUIRED_ENV = ["DJANGO_SECRET_KEY", "DB_HOST", "DB_PASSWORD", "SUPABASE_URL", "SUPABASE_ANON_KEY",
                "SUPABASE_SERVICE_ROLE_KEY", "REDIS_URL"]


@dataclass
class CheckResult:
    status: str
    latency_ms: int | None = None
    error: str | None = None
    recommendation: str | None = None
    details: dict = field(default_factory=dict)


def _timed(fn):
    t0 = time.monotonic()
    out = fn()
    return out, int((time.monotonic() - t0) * 1000)


def _q(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchall()


def db_connectivity() -> CheckResult:
    rows, ms = _timed(lambda: _q("SELECT version(), now()"))
    status = "healthy" if ms < 500 else "degraded"
    return CheckResult(status, ms, details={"version": rows[0][0][:60]},
                       recommendation=None if status == "healthy" else "High DB latency: check pooler / region")


def db_migrations() -> CheckResult:
    rows, ms = _timed(lambda: _q("SELECT count(*) FROM django.django_migrations WHERE app = 'core'"))
    applied = rows[0][0]
    tables = _q("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")[0][0]
    if applied == 0:
        return CheckResult("degraded", ms, "core SQL migration not recorded by Django", "Run: python manage.py migrate",
                           {"public_tables": tables})
    return CheckResult("healthy", ms, details={"core_migrations": applied, "public_tables": tables})


def db_rls() -> CheckResult:
    rows, ms = _timed(lambda: _q("""SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                                    WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND NOT c.relrowsecurity"""))
    if rows:
        return CheckResult("down", ms, f"{len(rows)} tables without RLS", "Enable RLS immediately",
                           {"tables": [r[0] for r in rows[:50]]})
    policies = _q("SELECT count(*) FROM pg_policies WHERE schemaname = 'public'")[0][0]
    return CheckResult("healthy", ms, details={"policies": policies})


def db_indexes() -> CheckResult:
    rows, ms = _timed(lambda: _q("""SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
                                    JOIN pg_namespace n ON n.oid = c.relnamespace
                                    WHERE n.nspname = 'public' AND NOT i.indisvalid"""))
    if rows:
        return CheckResult("degraded", ms, f"{len(rows)} invalid indexes", "REINDEX the listed indexes", {"indexes": [r[0] for r in rows]})
    return CheckResult("healthy", ms, details={"indexes": _q("SELECT count(*) FROM pg_indexes WHERE schemaname='public'")[0][0]})


def _supabase_get(path: str, service: bool = False) -> CheckResult:
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY or (service and not settings.SUPABASE_SERVICE_ROLE_KEY):
        return CheckResult("not_configured", error="SUPABASE_URL / keys missing", recommendation="Set Supabase env vars")
    key = settings.SUPABASE_SERVICE_ROLE_KEY if service else settings.SUPABASE_ANON_KEY
    try:
        resp, ms = _timed(lambda: requests.get(f"{settings.SUPABASE_URL}{path}", timeout=5,
                                               headers={"apikey": key, "Authorization": f"Bearer {key}"}))
    except requests.RequestException as e:
        return CheckResult("down", error=type(e).__name__, recommendation="Supabase unreachable from the backend")
    if resp.status_code != 200:
        return CheckResult("down", ms, f"HTTP {resp.status_code}")
    return CheckResult("healthy" if ms < 1500 else "degraded", ms, details={"items": len(resp.json()) if path.endswith("bucket") else None})


def supabase_auth() -> CheckResult:
    return _supabase_get("/auth/v1/health")


def supabase_storage() -> CheckResult:
    r = _supabase_get("/storage/v1/bucket", service=True)
    return r


def redis_check() -> CheckResult:
    import redis as redis_lib
    if not settings.REDIS_URL:
        return CheckResult("not_configured", error="REDIS_URL missing")
    key = f"growth:diag:{uuid.uuid4()}"  # dedicated diagnostic namespace, auto-expiring
    try:
        client = redis_lib.Redis.from_url(settings.REDIS_URL, socket_timeout=3)
        _, ms = _timed(lambda: (client.ping(), client.set(key, "1", ex=30), client.get(key), client.delete(key)))
    except Exception as e:  # noqa: BLE001
        return CheckResult("down", error=type(e).__name__, recommendation="Check Redis service / REDIS_URL")
    return CheckResult("healthy" if ms < 200 else "degraded", ms)


def celery_workers() -> CheckResult:
    from config.celery import app
    try:
        replies, ms = _timed(lambda: app.control.inspect(timeout=2).ping() or {})
    except Exception as e:  # noqa: BLE001
        return CheckResult("down", error=type(e).__name__, recommendation="Broker unreachable")
    if not replies:
        return CheckResult("down", ms, "no worker replied", "Start celery worker(s)")
    return CheckResult("healthy", ms, details={"workers": sorted(replies)})


def celery_beat() -> CheckResult:
    import redis as redis_lib
    try:
        ts = redis_lib.Redis.from_url(settings.REDIS_URL, socket_timeout=3).get("growth:heartbeat:beat")
    except Exception as e:  # noqa: BLE001
        return CheckResult("down", error=type(e).__name__)
    if not ts:
        return CheckResult("down", error="no beat heartbeat", recommendation="Start celery beat")
    age = time.time() - float(ts)
    return CheckResult("healthy" if age < 180 else "degraded", details={"heartbeat_age_s": int(age)})


def config_env() -> CheckResult:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    weak = ["DJANGO_DEBUG is on"] if settings.DEBUG else []
    if missing:
        return CheckResult("not_configured", error=f"missing: {', '.join(missing)}", recommendation="Complete .env (see .env.example)")
    return CheckResult("degraded" if weak else "healthy", details={"warnings": weak})


def api_self() -> CheckResult:
    rows, ms = _timed(lambda: _q("SELECT 1"))
    return CheckResult("healthy", ms)


REGISTRY = {
    "db.connectivity": db_connectivity, "db.migrations": db_migrations, "db.rls": db_rls, "db.indexes": db_indexes,
    "auth.health": supabase_auth, "storage.buckets": supabase_storage, "redis.ping": redis_check,
    "celery.ping": celery_workers, "celery.beat": celery_beat, "config.env": config_env, "api.self": api_self,
}
