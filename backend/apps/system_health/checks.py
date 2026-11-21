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
    return CheckResult("healthy" if ms < 2500 else "degraded", ms, details={"items": len(resp.json()) if path.endswith("bucket") else None})


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
        client.ping()  # connection opened outside the measurement
        _, ms = _timed(lambda: client.pipeline().set(key, "1", ex=30).get(key).delete(key).execute())
    except Exception as e:  # noqa: BLE001
        return CheckResult("down", error=type(e).__name__, recommendation="Check Redis service / REDIS_URL")
    return CheckResult("healthy" if ms < 250 else "degraded", ms)


def celery_workers() -> CheckResult:
    from celery import current_task

    from config.celery import app
    me = getattr(getattr(current_task, "request", None), "hostname", None) if current_task else None
    try:
        replies, ms = _timed(lambda: app.control.inspect(timeout=2).ping() or {})
    except Exception as e:  # noqa: BLE001
        return CheckResult("down", error=type(e).__name__, recommendation="Broker unreachable")
    if not replies and me:
        # this check is itself executing on a worker: with a single-process pool (Windows --pool=solo) that worker
        # cannot answer the ping while busy, yet it is demonstrably alive
        return CheckResult("healthy", ms, details={"workers": [me], "note": "self (single-process pool)"})
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


# ───────────── PROMPT 2: connector & automation probes ─────────────
# Connector checks aggregate the results of REAL provider tests (POST /connector-accounts/{id}/test, sends, syncs, webhooks).
# A connector without any real test is never reported healthy.
def _connector_summary(categories: tuple[str, ...] | None = None, providers: tuple[str, ...] | None = None) -> CheckResult:
    rows, ms = _timed(lambda: _q("""SELECT a.status, count(*), max(a.last_test_at) FROM public.tenant_connector_accounts a
                                    JOIN public.connector_providers p ON p.id = a.provider_id
                                    WHERE a.deleted_at IS NULL AND (%s::text[] IS NULL OR p.category = ANY(%s::text[]))
                                      AND (%s::text[] IS NULL OR p.code = ANY(%s::text[])) GROUP BY a.status""",
                                 [list(categories) if categories else None, list(categories) if categories else None,
                                  list(providers) if providers else None, list(providers) if providers else None]))
    counts = {r[0]: r[1] for r in rows}
    if not counts:
        return CheckResult("not_configured", ms, details={"accounts": 0})
    bad = sum(counts.get(s, 0) for s in ("failed", "expired", "error"))
    good = sum(counts.get(s, 0) for s in ("tested", "connected"))
    status = "down" if bad and not good else "degraded" if bad or not good else "healthy"
    return CheckResult(status, ms, None if status == "healthy" else f"{bad} failing / {good} tested", 
                       None if status == "healthy" else "Run a connection test from Connectors and fix failing accounts", {"by_status": counts})


def ai_providers() -> CheckResult:
    rows = _q("""SELECT p.code, (c.api_key_ciphertext IS NOT NULL) FROM public.ai_providers p JOIN public.ai_provider_configurations c
                 ON c.provider_id = p.id AND c.is_enabled AND c.deleted_at IS NULL""")
    if not rows:
        return CheckResult("not_configured", error="no AI provider configured", recommendation="PILOTE → Fournisseurs IA")
    stats = _q("""SELECT count(*) FILTER (WHERE status = 'succeeded'), count(*) FILTER (WHERE status <> 'succeeded')
                  FROM public.ai_execution_logs WHERE created_at > now() - interval '24 hours'""")[0]
    if stats[0] == 0 and stats[1] == 0:
        return CheckResult("unknown", details={"providers": [r[0] for r in rows]}, recommendation="Run 'Tester' from the AI providers page")
    return CheckResult("healthy" if stats[1] == 0 else "degraded" if stats[0] else "down", details={"ok_24h": stats[0], "errors_24h": stats[1]})


def email_send() -> CheckResult:
    s = _q("""SELECT count(*) FILTER (WHERE status IN ('sent','accepted','delivered')), count(*) FILTER (WHERE status = 'failed')
              FROM public.email_messages WHERE direction = 'outbound' AND created_at > now() - interval '24 hours'""")[0]
    base = _connector_summary(categories=("email",))
    if base.status == "not_configured":
        return base
    base.details |= {"sent_24h": s[0], "failed_24h": s[1]}
    if s[1] and not s[0]:
        base.status, base.error = "down", f"{s[1]} failed sends in 24h"
    return base


def email_receive() -> CheckResult:
    boxes = _q("""SELECT receive_mode, count(*), max(last_sync_at), count(*) FILTER (WHERE sync_error IS NOT NULL) FROM public.email_mailboxes
                  WHERE deleted_at IS NULL AND receive_mode <> 'none' GROUP BY receive_mode""")
    if not boxes:
        return CheckResult("not_configured", error="no receiving mailbox", recommendation="Configure a webhook, Gmail, Graph or IMAP mailbox")
    errors = sum(b[3] for b in boxes)
    inbound = _q("SELECT count(*) FROM public.email_messages WHERE direction = 'inbound' AND created_at > now() - interval '7 days'")[0][0]
    return CheckResult("degraded" if errors else "healthy" if inbound else "unknown", details={"modes": {b[0]: b[1] for b in boxes}, "sync_errors": errors,
                       "inbound_7d": inbound}, recommendation=None if inbound else "No inbound message received yet: send a test reply")


def webhooks_recent() -> CheckResult:
    r = _q("""SELECT count(*) FILTER (WHERE signature_valid), count(*) FILTER (WHERE signature_valid IS FALSE) FROM (
                SELECT signature_valid FROM public.email_webhook_events WHERE created_at > now() - interval '24 hours'
                UNION ALL SELECT signature_valid FROM public.whatsapp_webhook_events WHERE created_at > now() - interval '24 hours') x""")[0]
    if not r[0] and not r[1]:
        return CheckResult("unknown", details={"events_24h": 0})
    return CheckResult("degraded" if r[1] else "healthy", details={"valid_24h": r[0], "invalid_signature_24h": r[1]},
                       recommendation="Invalid signatures: check webhook secrets" if r[1] else None)


def scheduler_lag() -> CheckResult:
    late = _q("SELECT count(*) FROM public.tenant_schedulers WHERE status = 'active' AND deleted_at IS NULL AND next_run_at < now() - interval '10 minutes'")[0][0]
    stuck = _q("SELECT count(*) FROM public.scheduler_execution_runs WHERE status = 'running' AND started_at < now() - interval '1 hour'")[0][0]
    return CheckResult("degraded" if late or stuck else "healthy", details={"late": late, "stuck_running": stuck},
                       recommendation="Check Celery beat/worker" if late or stuck else None)


REGISTRY.update({
    "ai.providers": ai_providers, "email.send": email_send, "email.receive": email_receive, "webhooks.recent": webhooks_recent,
    "whatsapp.accounts": lambda: _connector_summary(providers=("whatsapp_cloud",)),
    "cms.wordpress": lambda: _connector_summary(categories=("cms",)),
    "social.accounts": lambda: _connector_summary(categories=("social",)),
    "scheduler.lag": scheduler_lag, "connectors.status": lambda: _connector_summary(),
})
