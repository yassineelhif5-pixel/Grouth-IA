"""Levels 3 & 4 of traceability: audit events, activity timeline, execution logs.

Level 2 (entity_history) is written by the database trigger in the SAME transaction, using the
actor/reason/correlation that Django pushed with app.set_context — so no write can escape history.
"""
from __future__ import annotations

import contextlib
import time
import uuid
from typing import Any

from django.utils import timezone

from apps.core.context import get_context, set_context
from apps.core.db import write_out_of_band
from apps.core.redaction import redact

from .models import ActivityEvent, AuditEvent, ExecutionLog, RecordAccessLog


def _actor_type(ctx) -> str:
    return ctx.actor_type if ctx.actor_type in ("user", "pilot", "system", "celery", "agent", "webhook", "anonymous") else "system"


def record_audit(action: str, module: str, *, entity_type: str | None = None, entity_id: Any = None,
                 description: str = "", before: dict | None = None, after: dict | None = None,
                 status: str = "success", source: str | None = None, secret_fields: tuple = (),
                 tenant_id: str | None = None, request=None) -> AuditEvent:
    ctx = get_context()
    meta = getattr(request, "META", {}) if request is not None else {}
    return AuditEvent.objects.create(
        tenant_id=tenant_id or ctx.tenant_id, actor_user_id=ctx.user_id, actor_type=_actor_type(ctx),
        action=action, module=module, entity_type=entity_type, entity_id=str(entity_id) if entity_id else None,
        description=description[:2000], before_data=redact(before, secret_fields) if before else None,
        after_data=redact(after, secret_fields) if after else None,
        source=source or ("celery" if ctx.actor_type == "celery" else "admin" if ctx.is_platform else "api"),
        status=status, ip_address=meta.get("REMOTE_ADDR") or None, user_agent=(meta.get("HTTP_USER_AGENT") or "")[:400] or None,
        request_id=ctx.request_id, correlation_id=ctx.correlation_id,
    )


def record_activity(event_type: str, module: str, *, entity_type: str | None = None, entity_id: Any = None,
                    description: str = "", product_id: str | None = None, metadata: dict | None = None,
                    tenant_id: str | None = None) -> ActivityEvent | None:
    ctx = get_context()
    tid = tenant_id or ctx.tenant_id
    if not tid:
        return None
    return ActivityEvent.objects.create(
        tenant_id=tid, user_id=ctx.user_id, product_id=product_id, event_type=event_type, module=module,
        entity_type=entity_type, entity_id=str(entity_id) if entity_id else None, description=description[:2000],
        metadata=redact(metadata or {}), correlation_id=ctx.correlation_id)


def record_access(entity_type: str, entity_id: Any, access_type: str, reason: str | None = None) -> None:
    ctx = get_context()
    if ctx.tenant_id:
        RecordAccessLog.objects.create(tenant_id=ctx.tenant_id, user_id=ctx.user_id, entity_type=entity_type,
                                       entity_id=str(entity_id), access_type=access_type, reason=reason,
                                       request_id=ctx.request_id, correlation_id=ctx.correlation_id)


@contextlib.contextmanager
def track_execution(module: str, operation: str, *, input_summary: dict | None = None,
                    execution_id: str | None = None, celery_task_id: str | None = None, retry_count: int = 0,
                    parent_execution_id: str | None = None):
    """Persist a level-4 execution record. Written on the separate `logs` connection, so it survives a
    rollback of the business transaction (a failed operation is still traced)."""
    ctx = get_context()
    exec_id = execution_id or str(uuid.uuid4())
    token_ctx = ctx.with_(execution_id=exec_id)
    set_context(token_ctx)
    started = timezone.now()
    t0 = time.monotonic()
    result: dict[str, Any] = {}
    status = "succeeded"
    error_code = error_message = None
    try:
        yield result
    except Exception as exc:  # noqa: BLE001 — re-raised below
        status, error_code, error_message = "failed", type(exc).__name__, str(exc)[:2000]
        raise
    finally:
        duration = int((time.monotonic() - t0) * 1000)
        write_out_of_band(lambda using: ExecutionLog.objects.using(using).create(
                tenant_id=ctx.tenant_id, module=module, operation=operation, execution_id=exec_id,
                parent_execution_id=parent_execution_id, workflow_execution_id=ctx.workflow_execution_id,
                webhook_event_id=ctx.webhook_event_id, request_id=ctx.request_id, celery_task_id=celery_task_id,
                status=status, started_at=started, completed_at=timezone.now(), duration_ms=duration,
                input_summary=redact(input_summary or {}), output_summary=redact(result) if result else None,
                error_code=error_code, error_message=error_message, retry_count=retry_count,
                cost_cents=result.get("cost_cents") if isinstance(result, dict) else None,
                correlation_id=ctx.correlation_id), ctx)
        set_context(ctx)
