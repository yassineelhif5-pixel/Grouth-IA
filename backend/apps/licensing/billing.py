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

PAID_PLANS = ["OFFRE_STARTER", "OFFRE_PRO", "OFFRE_PROFESSIONNELLE"]


class CheckoutSerializer(serializers.Serializer):
    plan_code = serializers.ChoiceField(choices=PAID_PLANS + ["STARTER", "GROWTH", "GROWTH_ENTREPRISE"])


class PlanCatalogView(GrowthAPIView):
    """Paid offers shown on the « Abonnement » page (monthly price incl. VAT)."""
    tenant_scoped = False

    def get(self, request):
        from apps.core.db import fetch_all_dict
        rows = fetch_all_dict("""SELECT code, name, description, price_monthly_cents, currency FROM public.subscription_plans
                                  WHERE code = ANY(%s) AND is_active ORDER BY sort_order""", [PAID_PLANS])
        return Response({"plans": rows, "online_payment": bool(settings.STRIPE_SECRET_KEY)})


class CheckoutView(GrowthAPIView):
    permission_map = {"POST": "billing.manage"}
    allow_without_subscription = True  # paying must stay possible once the trial is over

    def post(self, request):
        ser = CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        plan = ser.validated_data["plan_code"]
        if not settings.STRIPE_SECRET_KEY:
            raise BusinessError("Le paiement en ligne n'est pas encore activé (clés Stripe manquantes). Contactez-nous pour souscrire.",
                                "billing_not_configured", status_code=409)
        price = settings.STRIPE_PRICE_IDS.get(plan)
        row = fetch_one("SELECT name, price_monthly_cents, currency FROM public.subscription_plans WHERE code = %s AND is_active", [plan])
        if not price and not (row and row[1]):
            raise BusinessError("Aucun prix n'est défini pour cette offre", "billing_not_configured", status_code=409)
        line = ({"line_items[0][price]": price} if price else {  # no Stripe price id: price built from the plan (monthly, VAT incl.)
            "line_items[0][price_data][currency]": (row[2] or "EUR").lower(),
            "line_items[0][price_data][unit_amount]": row[1],
            "line_items[0][price_data][recurring][interval]": "month",
            "line_items[0][price_data][product_data][name]": f"Growth IA - {row[0]}"})
        tid = request.tenant.tenant_id
        front = settings.GROWTH["FRONTEND_URL"]
        resp = http("POST", "https://api.stripe.com/v1/checkout/sessions", provider="stripe", operation="checkout",
                    headers={"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"},
                    data={"mode": "subscription", **line, "line_items[0][quantity]": 1,
                          "subscription_data[metadata][tenant_id]": tid, "subscription_data[metadata][plan_code]": plan,
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
        elif event["type"] in ("customer.subscription.deleted", "invoice.payment_failed"):
            sub_id = obj.get("id") if event["type"] == "customer.subscription.deleted" else obj.get("subscription")
            new_status = "expired" if event["type"] == "customer.subscription.deleted" else "past_due"
            if tenant_id or sub_id:
                fetch_one("""UPDATE public.tenant_subscriptions SET status = %s, updated_at = now()
                              WHERE external_subscription_id = %s AND deleted_at IS NULL RETURNING 1""", [new_status, sub_id])
                record_audit(f"billing.subscription_{new_status}", "licensing", after={"subscription": sub_id, "event": event["id"]},
                             tenant_id=tenant_id, source="webhook")
        _ = get_context()
        return Response({"status": "processed"})
