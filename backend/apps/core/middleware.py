"""Creates the execution context for each HTTP request and echoes trace headers."""
from __future__ import annotations

import logging
import time

from .context import ExecutionContext, new_id, parse_uuid, reset_context, set_context

logger = logging.getLogger("growth.request")


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = new_id()  # always server-generated
        correlation_id = parse_uuid(request.headers.get("X-Correlation-ID")) or request_id
        ctx = ExecutionContext(request_id=request_id, correlation_id=correlation_id)
        token = set_context(ctx)
        request.growth_ctx = ctx
        started = time.monotonic()
        try:
            response = self.get_response(request)
        finally:
            reset_context(token)
        response["X-Request-ID"] = request_id
        response["X-Correlation-ID"] = correlation_id
        logger.info("request", extra={"method": request.method, "path": request.path,
                                      "status": getattr(response, "status_code", None),
                                      "duration_ms": int((time.monotonic() - started) * 1000)})
        return response
