"""Uniform error envelope: {"error": {"code", "message", "details", "request_id"}}."""
from __future__ import annotations

import logging

from django.db import IntegrityError
from django.db.utils import ProgrammingError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler
from rest_framework.views import set_rollback

from .context import get_context

logger = logging.getLogger("growth.errors")


class BusinessError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "business_error"

    def __init__(self, message: str, code: str | None = None, details: dict | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message, self.details = message, details or {}
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class QuotaExceeded(BusinessError):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    code = "quota_exceeded"


class ModuleNotAuthorized(BusinessError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "module_not_authorized"


def _persist_error(exc) -> None:
    """Server errors are stored in system_error_events (out of band, survives the rollback)."""
    if isinstance(exc, BusinessError) or getattr(exc, "status_code", 500) < 500:
        return
    try:
        import traceback

        from apps.core.db import write_out_of_band
        from apps.core.redaction import redact_text
        from apps.system_health.models import SystemErrorEvent

        ctx = get_context()
        write_out_of_band(lambda using: SystemErrorEvent.objects.using(using).create(
            tenant_id=ctx.tenant_id, service_code="api", error_code=type(exc).__name__,
            message=redact_text(str(exc))[:2000], stack_trace=redact_text(traceback.format_exc())[:8000],
            fingerprint=type(exc).__name__, request_id=ctx.request_id, correlation_id=ctx.correlation_id), ctx)
    except Exception:  # noqa: BLE001
        logger.exception("could not persist error event")


def _envelope(code: str, message: str, http: int, details=None) -> Response:
    return Response({"error": {"code": code, "message": message, "details": details or {},
                               "request_id": get_context().request_id}}, status=http)


def exception_handler(exc, context):
    set_rollback()  # never commit partial business writes when the request fails
    _persist_error(exc)
    if isinstance(exc, BusinessError):
        return _envelope(exc.code, exc.message, exc.status_code, exc.details)
    if isinstance(exc, IntegrityError):
        msg = str(exc).lower()
        if "row-level security" in msg or "immutable" in msg or "append-only" in msg:
            return _envelope("forbidden", "Operation not permitted", status.HTTP_403_FORBIDDEN)
        if "duplicate key" in msg or "already" in msg:
            return _envelope("conflict", "Resource already exists", status.HTTP_409_CONFLICT)
        return _envelope("integrity_error", "Data integrity violation", status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, ProgrammingError) and "row-level security" in str(exc).lower():
        return _envelope("forbidden", "Operation not permitted", status.HTTP_403_FORBIDDEN)
    response = drf_handler(exc, context)
    if response is None:
        logger.exception("unhandled error")
        return _envelope("internal_error", "Unexpected error", status.HTTP_500_INTERNAL_SERVER_ERROR)
    detail = response.data
    code = getattr(exc, "default_code", "error")
    message = detail.get("detail", "Invalid request") if isinstance(detail, dict) else "Invalid request"
    return _envelope(str(code), str(message), response.status_code, detail if isinstance(detail, dict) else {"errors": detail})
