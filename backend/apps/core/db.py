"""Propagate the execution context into the PostgreSQL session (transaction-local GUCs)."""
from __future__ import annotations

from django.db import connection, connections, transaction

from .context import ExecutionContext

GUCS = ("user_id", "tenant_id", "correlation_id", "request_id", "actor_type", "is_platform", "change_reason")


def apply_db_context(ctx: ExecutionContext, using: str = "default", session: bool = False) -> None:
    """Push the context into PostgreSQL. Transaction-local by default (requests); session-level for
    long-running Celery tasks that manage their own transactions (cleared by clear_db_context)."""
    if session:
        vals = [ctx.user_id or "", ctx.tenant_id or "", ctx.correlation_id or "", ctx.request_id or "", ctx.actor_type,
                "on" if ctx.is_platform else "", ctx.change_reason or ""]
        with connections[using].cursor() as cur:
            cur.execute("SELECT " + ", ".join(f"set_config('app.{g}', %s, false)" for g in GUCS), vals)
        return
    with connections[using].cursor() as cur:
        cur.execute(
            "SELECT app.set_context(%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s)",
            [ctx.user_id, ctx.tenant_id, ctx.correlation_id, ctx.request_id, ctx.actor_type,
             ctx.is_platform, ctx.change_reason],
        )


def fetch_one(sql: str, params: list | None = None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        return cur.fetchone()


def fetch_all_dict(sql: str, params: list | None = None) -> list[dict]:
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def write_out_of_band(fn, ctx: ExecutionContext):
    """Run `fn(using)` on the separate autocommit `logs` connection so technical records (executions,
    errors) persist even when the business transaction is rolled back."""
    with transaction.atomic(using="logs"):
        apply_db_context(ctx, using="logs")
        return fn("logs")


def clear_db_context(using: str = "default") -> None:
    with connections[using].cursor() as cur:
        cur.execute("SELECT " + ", ".join(f"set_config('app.{g}', '', false)" for g in GUCS))
