"""Inbound email & delivery webhooks. Each request: signature / secret check → anti-replay → tenant & mailbox
identification → persisted raw event (email_webhook_events) → idempotent ingestion."""
from __future__ import annotations

import base64
import json

from rest_framework.response import Response

from apps.core.db import fetch_one
from apps.core.webhooks import PublicWebhookView, claim_once, fresh, hmac_hex, safe_equals
from apps.integrations.gateway import get_credentials

from .services import ingest, parse_raw


class InboundEmailWebhook(PublicWebhookView):
    def post(self, request, mailbox_id, provider):
        self.platform_scope(request)
        mb = fetch_one("SELECT tenant_id, connector_account_id FROM public.email_mailboxes WHERE id = %s AND deleted_at IS NULL", [mailbox_id])
        if not mb:
            return Response(status=404)
        tenant_id, account_id = str(mb[0]), str(mb[1]) if mb[1] else None
        try:
            secrets = get_credentials(account_id) if account_id else {}
        except Exception:  # noqa: BLE001
            secrets = {}
        body = request.body
        valid, key, parsed, prov_id = False, None, None, None
        if provider == "mailgun":
            ts, tok, sig = request.POST.get("timestamp"), request.POST.get("token"), request.POST.get("signature")
            valid = bool(secrets.get("signing_key")) and fresh(ts) and safe_equals(hmac_hex(secrets["signing_key"], f"{ts}{tok}".encode()), sig or "")
            key = f"mailgun:{tok}"
            if valid:
                raw = request.POST.get("body-mime")
                parsed = parse_raw(raw.encode()) if raw else None
        elif provider == "postmark":
            auth = request.headers.get("Authorization", "")
            expected = "Basic " + base64.b64encode(f"{secrets.get('webhook_user', '')}:{secrets.get('webhook_secret', '')}".encode()).decode()
            valid = bool(secrets.get("webhook_secret")) and safe_equals(auth, expected)
            if valid:
                d = json.loads(body)
                prov_id, key = d.get("MessageID"), f"postmark:{d.get('MessageID')}"
                hdr = {h["Name"]: h["Value"] for h in d.get("Headers", [])}
                parsed = {"message_id": hdr.get("Message-ID") or f"<{d.get('MessageID')}@postmark>", "in_reply_to": hdr.get("In-Reply-To"),
                          "references": hdr.get("References"), "from": (d.get("FromFull") or {}).get("Email", "").lower(),
                          "to": [t["Email"].lower() for t in d.get("ToFull", [])], "cc": [c["Email"].lower() for c in d.get("CcFull", [])],
                          "subject": d.get("Subject", ""), "text": d.get("TextBody") or d.get("StrippedTextReply") or "",
                          "headers": {k: v for k, v in hdr.items() if k.lower() in ("auto-submitted", "x-autoreply", "precedence")},
                          "attachments": [{"filename": a["Name"], "content_type": a["ContentType"], "data": base64.b64decode(a["Content"])}
                                          for a in d.get("Attachments", [])]}
        elif provider == "sendgrid":
            token = request.query_params.get("token", "")
            valid = bool(secrets.get("inbound_token")) and safe_equals(token, secrets["inbound_token"])
            raw = request.POST.get("email")
            key = f"sendgrid:{hmac_hex('k', (raw or '').encode())}"
            parsed = parse_raw(raw.encode()) if valid and raw else None
        elif provider == "generic":
            ts, sig = request.headers.get("X-Growth-Timestamp", ""), request.headers.get("X-Growth-Signature", "")
            valid = bool(secrets.get("webhook_secret")) and fresh(ts) and safe_equals(hmac_hex(secrets["webhook_secret"], f"{ts}.".encode() + body), sig)
            if valid:
                d = json.loads(body)
                key = f"generic:{d.get('id') or hmac_hex('k', body)}"
                parsed = parse_raw(base64.b64decode(d["raw_base64"]))
        self.tenant_scope(request, tenant_id)
        ev = fetch_one("""INSERT INTO public.email_webhook_events (tenant_id, mailbox_id, provider, idempotency_key, event_type, payload, signature_valid, status)
                          VALUES (%s,%s,%s,%s,'inbound',%s::jsonb,%s,%s) ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING id""",
                       [tenant_id, mailbox_id, provider, key or f"invalid:{hmac_hex('k', body)}", json.dumps({"size": len(body)}), valid,
                        "received" if valid else "rejected"])
        if not valid:
            return Response({"error": "invalid signature"}, status=401)
        if not ev or not claim_once(f"email_webhook:{mailbox_id}", key, tenant_id):
            return Response({"status": "duplicate"})
        if not parsed:
            fetch_one("UPDATE public.email_webhook_events SET status = 'failed', error_message = 'unparseable' WHERE id = %s RETURNING 1", [ev[0]])
            return Response({"status": "ignored"})
        res = ingest(str(mailbox_id), parsed, provider_message_id=prov_id)
        fetch_one("UPDATE public.email_webhook_events SET status = %s, processed_at = now() WHERE id = %s RETURNING 1",
                  ["processed" if res["status"] == "stored" else "duplicate", ev[0]])
        return Response(res)


class DeliveryEventWebhook(PublicWebhookView):
    """Delivery status (Postmark / Mailgun / Resend / generic): updates outbound message status (accepted ≠ delivered)."""
    STATUS = {"Delivery": "delivered", "Bounce": "bounced", "SpamComplaint": "failed", "delivered": "delivered", "failed": "bounced",
              "email.delivered": "delivered", "email.bounced": "bounced", "email.complained": "failed"}

    def post(self, request, mailbox_id, provider):
        self.platform_scope(request)
        mb = fetch_one("SELECT tenant_id, connector_account_id FROM public.email_mailboxes WHERE id = %s", [mailbox_id])
        if not mb:
            return Response(status=404)
        secrets = get_credentials(str(mb[1])) if mb[1] else {}
        ts, sig = request.headers.get("X-Growth-Timestamp", ""), request.headers.get("X-Growth-Signature", "")
        token_ok = safe_equals(request.query_params.get("token", ""), secrets.get("webhook_secret", "-"))
        sig_ok = bool(secrets.get("webhook_secret")) and fresh(ts) and safe_equals(hmac_hex(secrets["webhook_secret"], f"{ts}.".encode() + request.body), sig)
        if not (token_ok or sig_ok):
            return Response({"error": "invalid signature"}, status=401)
        d = json.loads(request.body)
        etype = d.get("RecordType") or d.get("event") or d.get("type")
        pmid = d.get("MessageID") or (d.get("message") or {}).get("headers", {}).get("message-id") or (d.get("data") or {}).get("email_id")
        self.tenant_scope(request, str(mb[0]))
        if not claim_once(f"email_delivery:{mailbox_id}", f"{etype}:{pmid}:{d.get('id', '')}", str(mb[0])):
            return Response({"status": "duplicate"})
        status = self.STATUS.get(etype)
        msg = fetch_one("SELECT id FROM public.email_messages WHERE tenant_id = %s AND provider_message_id = %s", [str(mb[0]), pmid]) if pmid else None
        if msg and status:
            fetch_one("UPDATE public.email_messages SET status = %s WHERE id = %s RETURNING 1", [status, msg[0]])
            fetch_one("INSERT INTO public.email_delivery_events (tenant_id, message_id, provider, event_type, idempotency_key, details) VALUES (%s,%s,%s,%s,%s,%s::jsonb) RETURNING id",
                      [str(mb[0]), msg[0], provider, status if status != "failed" else "complained", f"{provider}:{etype}:{pmid}", json.dumps({"type": etype})])
        return Response({"status": "processed" if msg else "unknown_message"})
