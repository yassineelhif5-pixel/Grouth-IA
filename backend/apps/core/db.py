"""Propagate the execution context into the PostgreSQL session (transaction-local GUCs)."""
from __future__ import annotations

from django.db import connection, connections, transaction

from .context import ExecutionContext


def apply_db_context(ctx: ExecutionContext, using: str = "default") -> None:
    """Call app.set_context(); requires an open transaction (ATOMIC_REQUESTS / transaction.atomic)."""
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
