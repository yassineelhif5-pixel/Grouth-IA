"""Public webhook endpoints: no JWT, but signature verification + anti-replay + idempotency are mandatory."""
from __future__ import annotations

import hashlib
import hmac
import time

from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .context import new_id, set_context
from .db import apply_db_context, fetch_one


class WebhookThrottle(AnonRateThrottle):
    rate = "600/min"


class PublicWebhookView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [WebhookThrottle]

    def platform_scope(self, request) -> None:
        ctx = request.growth_ctx.with_(actor_type="webhook", is_platform=True, webhook_event_id=new_id())
        request.growth_ctx = ctx
        set_context(ctx)
        apply_db_context(ctx)

    def tenant_scope(self, request, tenant_id: str) -> None:
        ctx = request.growth_ctx.with_(tenant_id=str(tenant_id), is_platform=False)
        request.growth_ctx = ctx
        set_context(ctx)
        apply_db_context(ctx)


def hmac_hex(secret: str | bytes, payload: bytes, algo=hashlib.sha256) -> str:
    key = secret.encode() if isinstance(secret, str) else secret
    return hmac.new(key, payload, algo).hexdigest()


def safe_equals(a: str, b: str) -> bool:
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


def fresh(timestamp: float | int | str, tolerance: int = 300) -> bool:
    try:
        return abs(time.time() - float(timestamp)) <= tolerance
    except (TypeError, ValueError):
        return False


def claim_once(scope: str, key: str, tenant_id: str | None = None, days: int = 30) -> bool:
    """Anti-replay / idempotency: True only the first time (scope, key) is seen."""
    row = fetch_one("""INSERT INTO public.idempotency_keys (tenant_id, scope, key, expires_at)
                       VALUES (%s, %s, %s, now() + make_interval(days => %s)) ON CONFLICT DO NOTHING RETURNING id""",
                    [tenant_id, scope, key, days])
    return row is not None
