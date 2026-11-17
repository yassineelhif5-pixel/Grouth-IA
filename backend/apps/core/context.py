"""Request / task execution context (pure Python, framework independent).

The same context travels from the HTTP request to the database session (app.set_context),
to Celery tasks (message headers) and to structured logs, so one correlation_id links the
whole chain: frontend action → API request → transaction → task → provider call → audit.
"""
from __future__ import annotations

import contextvars
import uuid
from dataclasses import asdict, dataclass, field, replace

ACTOR_TYPES = ("user", "pilot", "system", "celery", "agent", "webhook", "anonymous")


def new_id() -> str:
    return str(uuid.uuid4())


def parse_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class ExecutionContext:
    request_id: str = field(default_factory=new_id)
    correlation_id: str = field(default_factory=new_id)
    user_id: str | None = None
    tenant_id: str | None = None
    actor_type: str = "anonymous"
    is_platform: bool = False
    execution_id: str | None = None
    workflow_execution_id: str | None = None
    webhook_event_id: str | None = None
    change_reason: str | None = None

    def with_(self, **changes) -> ExecutionContext:
        if "actor_type" in changes and changes["actor_type"] not in ACTOR_TYPES:
            raise ValueError(f"invalid actor_type {changes['actor_type']}")
        return replace(self, **changes)

    def to_headers(self) -> dict[str, str]:
        """Serialisable form propagated to Celery task headers."""
        return {f"growth_{k}": ("1" if v is True else "" if v is False else str(v))
                for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_headers(cls, headers: dict | None) -> ExecutionContext:
        h = {k[len("growth_"):]: v for k, v in (headers or {}).items() if str(k).startswith("growth_")}
        return cls(
            request_id=parse_uuid(h.get("request_id")) or new_id(),
            correlation_id=parse_uuid(h.get("correlation_id")) or new_id(),
            user_id=parse_uuid(h.get("user_id")),
            tenant_id=parse_uuid(h.get("tenant_id")),
            actor_type="celery",
            is_platform=h.get("is_platform") == "1",
            execution_id=parse_uuid(h.get("execution_id")),
            workflow_execution_id=parse_uuid(h.get("workflow_execution_id")),
            webhook_event_id=parse_uuid(h.get("webhook_event_id")),
            change_reason=h.get("change_reason") or None,
        )


_current: contextvars.ContextVar[ExecutionContext | None] = contextvars.ContextVar("growth_ctx", default=None)


def get_context() -> ExecutionContext:
    ctx = _current.get()
    if ctx is None:
        ctx = ExecutionContext(actor_type="system")
        _current.set(ctx)
    return ctx


def set_context(ctx: ExecutionContext) -> contextvars.Token:
    return _current.set(ctx)


def reset_context(token: contextvars.Token) -> None:
    _current.reset(token)
