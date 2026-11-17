"""TracedTask: every Celery task restores the originating context and is persisted in execution_logs."""
from __future__ import annotations

import logging
import uuid

from celery import Task

from apps.core.context import ExecutionContext, get_context, reset_context, set_context
from apps.core.db import apply_db_context, clear_db_context, fetch_one

logger = logging.getLogger("growth.tasks")


class TracedTask(Task):
    abstract = True
    autoretry_for = (ConnectionError, TimeoutError)
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    max_retries = 5
    module = "core"
    idempotent = False  # when True, the task id is registered in idempotency_keys before running

    def delay_traced(self, *args, **kwargs):
        """Like .delay() but propagates request/correlation/user/tenant ids through message headers."""
        ctx = get_context()
        return self.apply_async(args=args, kwargs=kwargs, headers=ctx.to_headers(), task_id=str(uuid.uuid4()))

    def __call__(self, *args, **kwargs):
        headers = getattr(self.request, "headers", None) or {}
        if not headers and self.request:
            headers = {k: v for k, v in vars(self.request).items() if str(k).startswith("growth_")}
        if any(str(k).startswith("growth_") for k in headers):
            ctx = ExecutionContext.from_headers(headers)
        else:  # eager mode / same thread: inherit the caller's context
            ctx = get_context().with_(actor_type="celery")
        ctx = ctx.with_(execution_id=self.request.id or str(uuid.uuid4()))
        caller = get_context()
        token = set_context(ctx)
        try:
            from apps.audit.services import track_execution
            with track_execution(self.module, self.name, execution_id=ctx.execution_id, celery_task_id=self.request.id,
                                 retry_count=self.request.retries or 0,
                                 input_summary={"args": [str(a)[:200] for a in args], "kwargs": list(kwargs)}) as out:
                # session-level context: the task manages its own (short) transactions, so a failure
                # status written before an exception is never rolled back with the work.
                apply_db_context(ctx, session=True)
                if self.idempotent and not self._claim(ctx):
                    out["skipped"] = "duplicate"
                    return None
                result = super().__call__(*args, **kwargs)
                if isinstance(result, dict):
                    out.update(result)
                return result
        finally:
            try:
                clear_db_context()
                if caller.tenant_id or caller.is_platform:  # eager execution inside a request: restore the caller's DB context
                    apply_db_context(caller)
            except Exception:  # noqa: BLE001
                logger.warning("could not reset db context")
            reset_context(token)

    def _claim(self, ctx: ExecutionContext) -> bool:
        row = fetch_one("""INSERT INTO public.idempotency_keys (tenant_id, scope, key, expires_at)
                           VALUES (%s, %s, %s, now() + interval '7 days') ON CONFLICT DO NOTHING RETURNING id""",
                        [ctx.tenant_id, self.name, self.request.id])
        return row is not None

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Final failure (retries exhausted): dead-letter record persisted in PostgreSQL."""
        from apps.core.db import write_out_of_band
        from apps.core.redaction import redact_text
        from apps.system_health.models import SystemErrorEvent

        ctx = get_context()
        try:
            write_out_of_band(lambda using: SystemErrorEvent.objects.using(using).create(
                tenant_id=ctx.tenant_id, service_code="celery", error_code="dead_letter:" + type(exc).__name__,
                message=redact_text(f"{self.name}: {exc}")[:2000], stack_trace=redact_text(str(einfo))[:8000],
                fingerprint=self.name, request_id=ctx.request_id, correlation_id=ctx.correlation_id), ctx)
        except Exception:  # noqa: BLE001
            logger.exception("could not persist dead letter")
        super().on_failure(exc, task_id, args, kwargs, einfo)


def platform_context() -> ExecutionContext:
    return ExecutionContext(actor_type="system", is_platform=True)


def run_in_platform_scope(fn):
    ctx = get_context().with_(is_platform=True, actor_type="celery")
    set_context(ctx)
    apply_db_context(ctx, session=True)
    return fn()


def run_in_tenant_scope(tenant_id: str, fn, user_id: str | None = None):
    """Switch a platform task to ONE tenant (RLS then restricts every query to that tenant)."""
    ctx = get_context().with_(tenant_id=str(tenant_id), is_platform=False, actor_type="celery", user_id=user_id)
    set_context(ctx)
    apply_db_context(ctx, session=True)
    return fn()
