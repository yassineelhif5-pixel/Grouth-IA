"""WhatsApp Business Cloud API: signed webhooks, consent (opt-in / STOP), 24-hour customer-service window,
approved templates outside the window, persisted conversations/messages/statuses."""
from __future__ import annotations

import json
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_one
from apps.core.exceptions import BusinessError
from apps.integrations.gateway import get_credentials, http
from apps.licensing.services import check_quota
from apps.permissions.growth import gate, register

STOP_WORDS = {"stop", "arret", "arrêt", "unsubscribe", "désabonner", "desabonner"}


def handle_payload(account_id: str, tenant_id: str, payload: dict) -> dict:
    stored = statuses = 0
    for entry in payload.get("entry", []):
        for ch in entry.get("changes", []):
            v = ch.get("value", {})
            names = {c["wa_id"]: c.get("profile", {}).get("name") for c in v.get("contacts", [])}
            for m in v.get("messages", []):
                if fetch_one("SELECT 1 FROM public.whatsapp_messages WHERE tenant_id = %s AND wa_message_id = %s", [tenant_id, m["id"]]):
                    continue
                body = (m.get("text") or {}).get("body") or (m.get("button") or {}).get("text") or f"[{m.get('type')}]"
                with transaction.atomic():
                    contact = fetch_one("""INSERT INTO public.whatsapp_contacts (tenant_id, wa_id, display_name, last_inbound_at) VALUES (%s,%s,%s, now())
                                           ON CONFLICT (tenant_id, wa_id) WHERE deleted_at IS NULL DO UPDATE SET last_inbound_at = now(),
                                             display_name = coalesce(EXCLUDED.display_name, whatsapp_contacts.display_name) RETURNING id, prospect_contact_id""",
                                        [tenant_id, m["from"], names.get(m["from"])])
                    conv = fetch_one("""INSERT INTO public.whatsapp_conversations (tenant_id, account_id, contact_id, is_unread, last_message_at)
                                        VALUES (%s,%s,%s,true, now()) ON CONFLICT (tenant_id, account_id, contact_id) WHERE deleted_at IS NULL
                                        DO UPDATE SET is_unread = true, last_message_at = now(), status = 'open' RETURNING id, assigned_to""",
                                     [tenant_id, account_id, contact[0]])
                    fetch_one("""INSERT INTO public.whatsapp_messages (tenant_id, conversation_id, direction, wa_message_id, message_type, body, status)
                                 VALUES (%s,%s,'inbound',%s,%s,%s,'received') RETURNING id""", [tenant_id, conv[0], m["id"], m.get("type", "text"), body[:4096]])
                    if body.strip().lower() in STOP_WORDS:
                        fetch_one("""UPDATE public.whatsapp_contacts SET consent_status = 'opted_out', consent_source = 'inbound STOP', consent_at = now()
                                      WHERE id = %s RETURNING 1""", [contact[0]])
                    if contact[1]:
                        fetch_one("""INSERT INTO public.crm_activities (tenant_id, prospect_id, activity_type, summary, channel, actor_type)
                                     SELECT %s, prospect_id, 'whatsapp', %s, 'whatsapp', 'prospect' FROM public.prospect_contacts WHERE id = %s RETURNING id""",
                                  [tenant_id, f"WhatsApp reçu : {body[:200]}", contact[1]])
                        fetch_one("UPDATE public.prospects SET last_activity_at = now() WHERE id = (SELECT prospect_id FROM public.prospect_contacts WHERE id = %s) RETURNING 1",
                                  [contact[1]])
                stored += 1
                from apps.notifications.service import notify
                notify("whatsapp.message", {"from": names.get(m["from"]) or m["from"]}, users=[str(conv[1])] if conv[1] else None,
                       permission="whatsapp.read", tenant_id=tenant_id)
            for st in v.get("statuses", []):
                status = {"sent": "sent", "delivered": "delivered", "read": "read", "failed": "failed"}.get(st.get("status"))
                if status:
                    fetch_one("UPDATE public.whatsapp_messages SET status = %s, error_message = %s WHERE tenant_id = %s AND wa_message_id = %s RETURNING 1",
                              [status, json.dumps(st.get("errors"))[:500] if st.get("errors") else None, tenant_id, st["id"]])
                    statuses += 1
    return {"messages": stored, "statuses": statuses}


def can_send_freeform(contact_id: str) -> bool:
    row = fetch_one("SELECT last_inbound_at FROM public.whatsapp_contacts WHERE id = %s", [contact_id])
    return bool(row and row[0] and row[0] > timezone.now() - timedelta(hours=24))


def send(conversation_id: str, text: str | None = None, template: str | None = None, language: str = "fr", variables: list[str] | None = None) -> dict:
    tid = get_context().tenant_id
    c = fetch_one("""SELECT c.account_id, c.contact_id, k.wa_id, k.consent_status, a.phone_number_id, a.connector_account_id
                       FROM public.whatsapp_conversations c JOIN public.whatsapp_contacts k ON k.id = c.contact_id JOIN public.whatsapp_accounts a ON a.id = c.account_id
                      WHERE c.id = %s AND c.tenant_id = %s""", [conversation_id, tid])
    if not c:
        raise BusinessError("conversation not found", "not_found", status_code=404)
    if c[3] != "opted_in":
        raise BusinessError("The contact has not opted in to WhatsApp messages", "no_consent", status_code=409)
    if text and not can_send_freeform(str(c[1])):
        raise BusinessError("Outside the 24-hour window: use an approved template", "window_closed", status_code=409)
    if template and not fetch_one("""SELECT 1 FROM public.whatsapp_templates WHERE account_id = %s AND name = %s AND language = %s AND status = 'approved'
                                      AND deleted_at IS NULL""", [c[0], template, language]):
        raise BusinessError("Template not approved", "template_not_approved", status_code=409)
    decision, approval = gate("whatsapp", "send", entity_type="whatsapp_conversations", entity_id=conversation_id,
                              payload={"text": text, "template": template, "language": language, "variables": variables or []})
    if decision != "execute":
        return {"status": decision, "approval_id": approval}
    return _send({"entity_id": conversation_id, "payload": {"text": text, "template": template, "language": language, "variables": variables or []}})


@register("whatsapp", "send")
def _send(approval: dict) -> dict:
    tid = get_context().tenant_id
    cid, p = approval["entity_id"], approval["payload"]
    c = fetch_one("""SELECT k.wa_id, a.phone_number_id, a.connector_account_id FROM public.whatsapp_conversations c JOIN public.whatsapp_contacts k ON k.id = c.contact_id
                      JOIN public.whatsapp_accounts a ON a.id = c.account_id WHERE c.id = %s""", [cid])
    if not c[2]:
        raise BusinessError("WhatsApp account not connected", "connector_not_configured", status_code=409)
    check_quota(tid, "whatsapp.sends.daily")
    token = get_credentials(str(c[2]))["access_token"]
    body = ({"messaging_product": "whatsapp", "to": c[0], "type": "text", "text": {"body": p["text"]}} if p.get("text") else
            {"messaging_product": "whatsapp", "to": c[0], "type": "template", "template": {"name": p["template"], "language": {"code": p["language"]},
             "components": [{"type": "body", "parameters": [{"type": "text", "text": v} for v in p.get("variables", [])]}] if p.get("variables") else []}})
    mid = fetch_one("""INSERT INTO public.whatsapp_messages (tenant_id, conversation_id, direction, message_type, body, template_name, status, sent_by)
                       VALUES (%s,%s,'outbound',%s,%s,%s,'queued',%s) RETURNING id""",
                    [tid, cid, "text" if p.get("text") else "template", p.get("text"), p.get("template"), get_context().user_id])[0]
    try:
        d = http("POST", f"https://graph.facebook.com/v21.0/{c[1]}/messages", provider="whatsapp_cloud", operation="send", account_id=str(c[2]),
                 headers={"Authorization": f"Bearer {token}"}, json=body).json()
    except BusinessError as e:
        fetch_one("UPDATE public.whatsapp_messages SET status = 'failed', error_message = %s WHERE id = %s RETURNING 1", [e.message, mid])
        raise
    fetch_one("UPDATE public.whatsapp_messages SET status = 'sent', wa_message_id = %s WHERE id = %s RETURNING 1", [d["messages"][0]["id"], mid])
    fetch_one("UPDATE public.whatsapp_conversations SET last_message_at = now() WHERE id = %s RETURNING 1", [cid])
    record_audit("whatsapp.sent", "whatsapp", entity_type="whatsapp_messages", entity_id=mid, after={"template": p.get("template")})
    record_activity("whatsapp.sent", "whatsapp", entity_type="whatsapp_conversations", entity_id=cid)
    return {"status": "sent", "message_id": str(mid)}
