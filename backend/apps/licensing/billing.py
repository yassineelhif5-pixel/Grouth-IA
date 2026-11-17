"""Licence upgrade: Stripe Checkout + signed webhook → plan activation (idempotent, audited)."""
from __future__ import annotations

import json

from django.conf import settings
from django.db import transaction
from rest_framework import serializers
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.context import get_context
from apps.core.db import fetch_one
from apps.core.exceptions import BusinessError
from apps.core.views import GrowthAPIView
from apps.core.webhooks import PublicWebhookView, claim_once, fresh, hmac_hex, safe_equals
from apps.integrations.gateway import http

from .services import change_plan


class CheckoutSerializer(serializers.Serializer):
    plan_code = serializers.ChoiceField(choices=["STARTER", "GROWTH", "GROWTH_ENTREPRISE"])


class CheckoutView(GrowthAPIView):
    permission_map = {"POST": "billing.manage"}

    def post(self, request):
        ser = CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        plan = ser.validated_data["plan_code"]
        price = settings.STRIPE_PRICE_IDS.get(plan)
        if not settings.STRIPE_SECRET_KEY or not price:
            raise BusinessError("Online payment is not configured (Stripe keys / price ids)", "billing_not_configured", status_code=409)
        tid = request.tenant.tenant_id
        front = settings.GROWTH["FRONTEND_URL"]
        resp = http("POST", "https://api.stripe.com/v1/checkout/sessions", provider="stripe", operation="checkout",
                    headers={"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"},
                    data={"mode": "subscription", "line_items[0][price]": price, "line_items[0][quantity]": 1,
                          "client_reference_id": tid, "metadata[tenant_id]": tid, "metadata[plan_code]": plan,
                          "success_url": f"{front}/t/{tid}/subscription?checkout=success",
                          "cancel_url": f"{front}/t/{tid}/subscription?checkout=cancel"})
        record_audit("billing.checkout_created", "licensing", after={"plan": plan})
        return Response({"url": resp.json().get("url")})


def verify_stripe_signature(payload: bytes, header: str, secret: str, tolerance: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    ts, sig = parts.get("t"), parts.get("v1")
    if not ts or not sig or not fresh(ts, tolerance):
        return False
    return safe_equals(hmac_hex(secret, f"{ts}.".encode() + payload), sig)


class StripeWebhookView(PublicWebhookView):
    def post(self, request):
        payload = request.body
        if not settings.STRIPE_WEBHOOK_SECRET or not verify_stripe_signature(payload, request.headers.get("Stripe-Signature", ""),
                                                                            settings.STRIPE_WEBHOOK_SECRET):
            return Response({"error": "invalid signature"}, status=400)
        event = json.loads(payload)
        self.platform_scope(request)
        if not claim_once("stripe", event["id"]):
            return Response({"status": "duplicate"})
        obj = event.get("data", {}).get("object", {})
        meta = obj.get("metadata") or {}
        tenant_id, plan = meta.get("tenant_id") or obj.get("client_reference_id"), meta.get("plan_code")
        fetch_one("""INSERT INTO public.subscription_payment_events (tenant_id, provider, idempotency_key, event_type, payload)
                     VALUES (%s, 'stripe', %s, %s, %s::jsonb) RETURNING id""",
                  [tenant_id, event["id"], event["type"], json.dumps({"id": obj.get("id"), "status": obj.get("status"),
                                                                     "amount_total": obj.get("amount_total"), "plan": plan})])
        if event["type"] == "checkout.session.completed" and obj.get("payment_status") in ("paid", "no_payment_required") and tenant_id and plan:
            self.tenant_scope(request, tenant_id)
            with transaction.atomic():
                sub = change_plan(tenant_id, plan, reason=f"Stripe payment confirmed ({event['id']})")
                fetch_one("""UPDATE public.tenant_subscriptions SET external_customer_id = %s, external_subscription_id = %s
                              WHERE id = %s RETURNING 1""", [obj.get("customer"), obj.get("subscription"), sub.id])
                fetch_one("""INSERT INTO public.subscription_payments (tenant_id, amount_cents, currency, status, provider, external_payment_id, paid_at)
                             VALUES (%s, %s, upper(%s), 'succeeded', 'stripe', %s, now()) RETURNING id""",
                          [tenant_id, obj.get("amount_total") or 0, obj.get("currency") or "eur", obj.get("payment_intent") or obj.get("id")])
            record_audit("billing.payment_confirmed", "licensing", after={"plan": plan, "event": event["id"]}, tenant_id=tenant_id,
                         source="webhook")
            from apps.notifications.service import notify
            notify("report.ready", {"title": f"Abonnement {plan} activé"}, permission="licenses.read", tenant_id=tenant_id)
        _ = get_context()
        return Response({"status": "processed"})
