import logging

from .context import get_context


class ContextFilter(logging.Filter):
    """Adds request/correlation/tenant ids to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = get_context()
        record.request_id = ctx.request_id
        record.correlation_id = ctx.correlation_id
        record.tenant_id = ctx.tenant_id or ""
        return True
