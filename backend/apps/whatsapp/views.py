import json

from rest_framework.response import Response

from apps.core.crud import crud
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.core.views import GrowthAPIView
from apps.core.webhooks import PublicWebhookView, claim_once, hmac_hex, safe_equals
from apps.integrations.gateway import get_credentials

from . import services as s
from .models import WhatsappAccount, WhatsappContact, WhatsappTemplate

AccountViewSet = crud(WhatsappAccount, module="whatsapp", perm="whatsapp", write="send")
TemplateViewSet = crud(WhatsappTemplate, module="whatsapp", perm="whatsapp", write="send", filters=["account", "status"])
ContactViewSet = crud(WhatsappContact, module="whatsapp", perm="whatsapp", write="send", filters=["consent_status"], search=["wa_id", "display_name"])


class ConversationsView(GrowthAPIView):
    permission_map = {"GET": "whatsapp.read"}
    required_module = "whatsapp"

    def get(self, request):
        return Response(fetch_all_dict("""SELECT c.id, c.status, c.is_unread, c.assigned_to, c.last_message_at, k.wa_id, k.display_name, k.consent_status,
                                                 k.last_inbound_at > now() - interval '24 hours' AS window_open,
                                                 (SELECT left(body, 160) FROM public.whatsapp_messages m WHERE m.conversation_id = c.id ORDER BY created_at DESC LIMIT 1) AS last_message
                                            FROM public.whatsapp_conversations c JOIN public.whatsapp_contacts k ON k.id = c.contact_id
                                           WHERE c.tenant_id = %s AND c.deleted_at IS NULL ORDER BY c.last_message_at DESC NULLS LAST LIMIT 200""",
                                       [request.tenant.tenant_id]))


class ConversationView(GrowthAPIView):
    permission_map = {"GET": "whatsapp.read", "POST": "whatsapp.send"}
    required_module = "whatsapp"

    def get(self, request, cid):
        fetch_one("UPDATE public.whatsapp_conversations SET is_unread = false WHERE id = %s AND tenant_id = %s RETURNING 1", [cid, request.tenant.tenant_id])
        return Response(fetch_all_dict("""SELECT id, direction, message_type, body, template_name, status, error_message, created_at FROM public.whatsapp_messages
                                           WHERE conversation_id = %s AND tenant_id = %s ORDER BY created_at""", [cid, request.tenant.tenant_id]))

    def post(self, request, cid):
        d = request.data
        if d.get("action") == "assign":
            fetch_one("UPDATE public.whatsapp_conversations SET assigned_to = %s WHERE id = %s AND tenant_id = %s RETURNING 1", [d["user_id"], cid, request.tenant.tenant_id])
            return Response({"status": "assigned"})
        if d.get("action") == "consent":
            if d.get("consent_status") not in ("opted_in", "opted_out"):
                raise BusinessError("invalid consent", "invalid")
            fetch_one("""UPDATE public.whatsapp_contacts SET consent_status = %s, consent_source = %s, consent_at = now()
                          WHERE id = (SELECT contact_id FROM public.whatsapp_conversations WHERE id = %s AND tenant_id = %s) RETURNING 1""",
                      [d["consent_status"], d.get("source") or f"user:{request.user.id}", cid, request.tenant.tenant_id])
            return Response({"status": d["consent_status"]})
        return Response(s.send(str(cid), d.get("text"), d.get("template"), d.get("language", "fr"), d.get("variables")))


class WhatsAppWebhook(PublicWebhookView):
    """GET: Meta verification (hub.verify_token). POST: X-Hub-Signature-256 (app secret) + dedup."""
    def _account(self, account_id):
        row = fetch_one("SELECT tenant_id, connector_account_id FROM public.whatsapp_accounts WHERE id = %s AND deleted_at IS NULL", [account_id])
        if not row or not row[1]:
            return None, {}
        return str(row[0]), get_credentials(str(row[1]))

    def get(self, request, account_id):
        self.platform_scope(request)
        _, cred = self._account(account_id)
        if request.query_params.get("hub.mode") == "subscribe" and cred.get("verify_token") and safe_equals(request.query_params.get("hub.verify_token", ""), cred["verify_token"]):
            from django.http import HttpResponse
            return HttpResponse(request.query_params.get("hub.challenge", ""), content_type="text/plain")
        return Response(status=403)

    def post(self, request, account_id):
        self.platform_scope(request)
        tenant_id, cred = self._account(account_id)
        if not tenant_id:
            return Response(status=404)
        sig = request.headers.get("X-Hub-Signature-256", "").removeprefix("sha256=")
        valid = bool(cred.get("app_secret")) and safe_equals(hmac_hex(cred["app_secret"], request.body), sig)
        self.tenant_scope(request, tenant_id)
        key = "wa:" + hmac_hex("k", request.body)
        fetch_one("""INSERT INTO public.whatsapp_webhook_events (tenant_id, account_id, idempotency_key, signature_valid, event_type, payload)
                     VALUES (%s,%s,%s,%s,'callback',%s::jsonb) ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING id""",
                  [tenant_id, account_id, key, valid, json.dumps({"size": len(request.body)}) if not valid else request.body.decode()])
        if not valid:
            return Response({"error": "invalid signature"}, status=401)
        if not claim_once(f"whatsapp:{account_id}", key, tenant_id):
            return Response({"status": "duplicate"})
        return Response(s.handle_payload(str(account_id), tenant_id, json.loads(request.body)))
