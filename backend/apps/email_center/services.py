"""Email Center: sending through provider APIs, receiving (webhooks / Gmail / Graph / IMAP), RFC-5322 threading,
deduplication, attachments in private Storage, rule+AI classification, THOR drafts, CRM updates.

Threading never relies on the subject or the sender alone: In-Reply-To / References → provider thread id → new thread.
Inbound content is untrusted data: it is wrapped before any AI call and can never change instructions or permissions."""
from __future__ import annotations

import email
import email.policy
import hashlib
import json
import re
import smtplib
import ssl
import uuid
from base64 import urlsafe_b64encode
from email.message import EmailMessage
from email.utils import getaddresses, make_msgid, parseaddr

from django.conf import settings
from django.db import transaction

from apps.ai_providers.gateway import AINotConfigured, complete, wrap_untrusted
from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.integrations.gateway import get_credentials, http, load_account
from apps.licensing.services import check_quota

CATEGORIES = ["interested", "demo_requested", "pricing_request", "information_request", "meeting_request", "negotiation", "not_interested",
              "unsubscribe", "out_of_office", "automatic_reply", "human_review_required"]
LABEL_FOR = {"interested": "interested", "demo_requested": "demo_requested", "meeting_request": "demo_requested", "pricing_request": "follow_up",
             "information_request": "follow_up", "negotiation": "follow_up", "unsubscribe": "unsubscribed"}
PROSPECT_STATUS = {"interested": "interested", "demo_requested": "demo_requested", "meeting_request": "demo_requested", "negotiation": "negotiation",
                   "pricing_request": "interested", "not_interested": "lost", "unsubscribe": "unsubscribed"}
UNSUB_RE = re.compile(r"\b(unsubscribe|désabonn|desabonn|ne plus recevoir|stop (emails?|mails?)|remove me|retirez[- ]moi)\b", re.I)
OOO_RE = re.compile(r"\b(out of (the )?office|absent|en congés?|auto(matic)? reply|réponse automatique|i am away|je suis absent)\b", re.I)


# ───────────────────────────── Sending ─────────────────────────────
def _mailbox(mailbox_id: str) -> dict:
    rows = fetch_all_dict("""SELECT m.id, m.tenant_id, m.address, m.display_name, m.connector_account_id, m.send_enabled, m.status, m.receive_mode
                               FROM public.email_mailboxes m WHERE m.id = %s AND m.deleted_at IS NULL""", [mailbox_id])
    if not rows:
        raise BusinessError("mailbox not found", "not_found", status_code=404)
    return rows[0]


def _suppressed(tenant_id: str, address: str) -> bool:
    return bool(fetch_one("SELECT 1 FROM public.prospect_suppression_lists WHERE tenant_id = %s AND lower(email) = lower(%s) AND deleted_at IS NULL",
                          [tenant_id, address]))


def _deliver(mb: dict, msg: EmailMessage, thread_hint: str | None) -> tuple[str | None, str, str | None]:
    """Returns (provider_message_id, status, provider_thread_id). status: sent | accepted."""
    acc = load_account(str(mb["connector_account_id"]))
    prov = acc.provider
    if prov == "smtp":
        c = get_credentials(acc.id)
        with smtplib.SMTP(acc.settings["host"], int(acc.settings.get("port", 587)), timeout=30) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(c["username"], c["password"])
            s.send_message(msg)
        return None, "sent", None
    if prov in ("gmail", "google_workspace"):
        from apps.integrations.providers import access_token
        body = {"raw": urlsafe_b64encode(msg.as_bytes()).decode()}
        if thread_hint:
            body["threadId"] = thread_hint
        d = http("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", provider=prov, operation="send", account_id=acc.id,
                 headers={"Authorization": f"Bearer {access_token(acc.id)}"}, json=body).json()
        return d.get("id"), "accepted", d.get("threadId")
    if prov in ("microsoft_graph", "outlook"):
        from apps.integrations.providers import access_token
        h = {"Authorization": f"Bearer {access_token(acc.id)}", "Content-Type": "text/plain"}
        draft = http("POST", "https://graph.microsoft.com/v1.0/me/messages", provider=prov, operation="create", account_id=acc.id,
                     headers=h, data=urlsafe_b64encode(msg.as_bytes()).decode().replace("-", "+").replace("_", "/")).json()
        http("POST", f"https://graph.microsoft.com/v1.0/me/messages/{draft['id']}/send", provider=prov, operation="send", account_id=acc.id,
             headers={"Authorization": h["Authorization"]})
        return draft.get("internetMessageId") or draft["id"], "accepted", draft.get("conversationId")
    key = get_credentials(acc.id).get("api_key")
    frm, to, subj = msg["From"], msg["To"], msg["Subject"]
    text = msg.get_body(("plain",)).get_content() if msg.get_body(("plain",)) else ""
    extra = {k: msg[k] for k in ("Message-ID", "In-Reply-To", "References") if msg[k]}
    if prov == "sendgrid":
        r = http("POST", "https://api.sendgrid.com/v3/mail/send", provider=prov, operation="send", account_id=acc.id,
                 headers={"Authorization": f"Bearer {key}"},
                 json={"personalizations": [{"to": [{"email": a} for _, a in getaddresses([to])]}], "from": {"email": parseaddr(frm)[1], "name": parseaddr(frm)[0]},
                       "subject": subj, "content": [{"type": "text/plain", "value": text}], "headers": extra})
        return r.headers.get("X-Message-Id"), "accepted", None
    if prov == "postmark":
        d = http("POST", "https://api.postmarkapp.com/email", provider=prov, operation="send", account_id=acc.id,
                 headers={"X-Postmark-Server-Token": key, "Accept": "application/json"},
                 json={"From": frm, "To": to, "Subject": subj, "TextBody": text, "Headers": [{"Name": k, "Value": v} for k, v in extra.items()],
                       "MessageStream": acc.settings.get("stream", "outbound")}).json()
        return d.get("MessageID"), "accepted", None
    if prov == "mailgun":
        d = http("POST", f"{acc.settings.get('base_url', 'https://api.mailgun.net')}/v3/{acc.settings['domain']}/messages.mime", provider=prov,
                 operation="send", account_id=acc.id, auth=("api", key), data={"to": to}, files={"message": ("msg.eml", msg.as_bytes())}).json()
        return d.get("id"), "accepted", None
    if prov == "resend":
        d = http("POST", "https://api.resend.com/emails", provider=prov, operation="send", account_id=acc.id, headers={"Authorization": f"Bearer {key}"},
                 json={"from": frm, "to": [a for _, a in getaddresses([to])], "subject": subj, "text": text, "headers": extra}).json()
        return d.get("id"), "accepted", None
    if prov == "brevo":
        d = http("POST", "https://api.brevo.com/v3/smtp/email", provider=prov, operation="send", account_id=acc.id, headers={"api-key": key},
                 json={"sender": {"email": parseaddr(frm)[1], "name": parseaddr(frm)[0]}, "to": [{"email": a} for _, a in getaddresses([to])],
                       "subject": subj, "textContent": text, "headers": extra}).json()
        return d.get("messageId"), "accepted", None
    raise BusinessError(f"Sending through {prov} is not supported", "not_implemented", status_code=501)


def send_email(mailbox_id: str, to: list[str], subject: str, body: str, *, conversation_id: str | None = None, cc: list[str] | None = None,
               prospect_id: str | None = None, campaign_id: str | None = None, product_id: str | None = None, draft_id: str | None = None) -> str:
    ctx = get_context()
    mb = _mailbox(mailbox_id)
    if str(mb["tenant_id"]) != ctx.tenant_id:
        raise BusinessError("mailbox not found", "not_found", status_code=404)
    if not mb["send_enabled"] or not mb["connector_account_id"]:
        raise BusinessError("Sending is not configured for this mailbox", "connector_not_configured", status_code=409)
    blocked = [a for a in to + (cc or []) if _suppressed(ctx.tenant_id, a)]
    if blocked:
        raise BusinessError(f"Recipient(s) unsubscribed or suppressed: {', '.join(blocked)}", "recipient_suppressed", status_code=409)
    check_quota(ctx.tenant_id, "email.sends.daily")
    domain = mb["address"].split("@")[-1]
    msg = EmailMessage(policy=email.policy.SMTP)
    msg["From"] = f'{mb["display_name"] or ""} <{mb["address"]}>'.strip()
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    mid = make_msgid(domain=domain)
    msg["Message-ID"] = mid
    thread_hint = None
    if conversation_id:
        last = fetch_one("""SELECT message_id_header, coalesce(references_header,''), provider_thread_id FROM public.email_messages
                             WHERE conversation_id = %s ORDER BY coalesce(received_at, sent_at, created_at) DESC LIMIT 1""", [conversation_id])
        if last:
            msg["In-Reply-To"] = last[0]
            msg["References"] = (last[1] + " " + last[0]).strip()
            thread_hint = last[2]
    msg.set_content(body)
    with transaction.atomic():
        if not conversation_id:
            conversation_id = str(fetch_one("""INSERT INTO public.email_conversations (tenant_id, mailbox_id, thread_id, subject, prospect_id, campaign_id, product_id, last_outbound_at)
                                               VALUES (%s,%s,%s,%s,%s,%s,%s, now()) RETURNING id""",
                                            [ctx.tenant_id, mailbox_id, mid, subject, prospect_id, campaign_id, product_id])[0])
        row = fetch_one("""INSERT INTO public.email_messages (tenant_id, conversation_id, mailbox_id, message_id_header, in_reply_to, references_header, direction,
                             from_email, to_emails, cc_emails, subject, body_text, prospect_id, campaign_id, status, sent_by)
                           SELECT %s,%s,%s,%s,%s,%s,'outbound',%s,%s,%s,%s,%s, coalesce(%s, c.prospect_id), coalesce(%s, c.campaign_id), 'queued', %s
                             FROM public.email_conversations c WHERE c.id = %s RETURNING id""",
                        [ctx.tenant_id, conversation_id, mailbox_id, mid, msg["In-Reply-To"], msg["References"], mb["address"], to, cc or [], subject, body,
                         prospect_id, campaign_id, ctx.user_id, conversation_id])
    message_id = str(row[0])
    try:
        provider_id, status, thread = _deliver(mb, msg, thread_hint)
    except (BusinessError, smtplib.SMTPException, OSError) as e:
        err = getattr(e, "message", None) or f"{type(e).__name__}: {e}"
        fetch_one("UPDATE public.email_messages SET status = 'failed', error_message = %s WHERE id = %s RETURNING 1", [err[:1000], message_id])
        fetch_one("INSERT INTO public.email_provider_errors (tenant_id, mailbox_id, error_code, error_message) VALUES (%s,%s,'send_failed',%s) RETURNING id",
                  [ctx.tenant_id, mailbox_id, err[:1000]])
        record_audit("email.send_failed", "email_center", entity_type="email_messages", entity_id=message_id, status="failure", description=err[:500])
        raise BusinessError(f"Email not sent: {err[:300]}", "send_failed", status_code=502) from e
    with transaction.atomic():
        fetch_one("""UPDATE public.email_messages SET status = %s, provider_message_id = %s, provider_thread_id = coalesce(%s, provider_thread_id), sent_at = now()
                      WHERE id = %s RETURNING 1""", [status, provider_id, thread, message_id])
        fetch_one("INSERT INTO public.email_delivery_events (tenant_id, message_id, provider, event_type, idempotency_key) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                  [ctx.tenant_id, message_id, load_account(str(mb["connector_account_id"])).provider, "sent" if status == "sent" else "queued", f"send:{message_id}"])
        fetch_one("UPDATE public.email_conversations SET last_outbound_at = now(), last_message_at = now() WHERE id = %s RETURNING 1", [conversation_id])
        if draft_id:
            fetch_one("UPDATE public.email_reply_drafts SET status = 'sent', sent_message_id = %s WHERE id = %s RETURNING 1", [message_id, draft_id])
        pid = fetch_one("SELECT prospect_id FROM public.email_conversations WHERE id = %s", [conversation_id])[0]
        if pid:
            fetch_one("UPDATE public.prospects SET last_activity_at = now() WHERE id = %s RETURNING 1", [pid])
            fetch_one("""INSERT INTO public.crm_activities (tenant_id, prospect_id, activity_type, summary, channel, actor_type, entity_ref)
                         VALUES (%s,%s,'email',%s,'email','user',%s::jsonb) RETURNING id""",
                      [ctx.tenant_id, pid, f"Email envoyé : {subject}"[:500], json.dumps({"email_message_id": message_id})])
    record_audit("email.sent", "email_center", entity_type="email_messages", entity_id=message_id,
                 after={"to": to, "provider_message_id": provider_id, "status": status, "campaign_id": campaign_id, "prospect_id": prospect_id})
    return message_id


# ───────────────────────────── Receiving ─────────────────────────────
def parse_raw(raw: bytes) -> dict:
    m = email.message_from_bytes(raw, policy=email.policy.default)
    body = m.get_body(("plain",))
    text = body.get_content() if body else ""
    if not text and (h := m.get_body(("html",))):
        text = re.sub(r"<[^>]+>", " ", h.get_content())
    atts = [{"filename": p.get_filename() or "attachment", "content_type": p.get_content_type(), "data": p.get_payload(decode=True) or b""}
            for p in m.iter_attachments()]
    return {"message_id": m.get("Message-ID") or f"<{uuid.uuid4()}@missing.growth-ia>", "in_reply_to": m.get("In-Reply-To"),
            "references": m.get("References"), "from": parseaddr(m.get("From", ""))[1].lower(), "to": [a.lower() for _, a in getaddresses(m.get_all("To", []))],
            "cc": [a.lower() for _, a in getaddresses(m.get_all("Cc", []))], "subject": m.get("Subject", ""), "text": text,
            "date": m.get("Date"), "headers": {k: str(v)[:500] for k, v in m.items() if k.lower() in ("auto-submitted", "x-autoreply", "x-autorespond",
                                                                                                     "precedence", "list-unsubscribe", "x-failed-recipients", "return-path")},
            "attachments": atts}


def _find_thread(tenant_id: str, mailbox_id: str, p: dict, provider_thread_id: str | None) -> str | None:
    refs = [r for r in re.findall(r"<[^>]+>", f"{p.get('in_reply_to') or ''} {p.get('references') or ''}")]
    if refs:
        row = fetch_one("""SELECT conversation_id FROM public.email_messages WHERE tenant_id = %s AND mailbox_id = %s AND message_id_header = ANY(%s)
                            ORDER BY created_at DESC LIMIT 1""", [tenant_id, mailbox_id, refs])
        if row:
            return str(row[0])
    if provider_thread_id:
        row = fetch_one("""SELECT conversation_id FROM public.email_messages WHERE tenant_id = %s AND mailbox_id = %s AND provider_thread_id = %s
                            ORDER BY created_at DESC LIMIT 1""", [tenant_id, mailbox_id, provider_thread_id])
        if row:
            return str(row[0])
    return None


def _store_attachment(tenant_id: str, mailbox_id: str, message_id: str, a: dict) -> None:
    data, ctype = a["data"], a["content_type"]
    sha = hashlib.sha256(data).hexdigest()
    status, path = "not_scanned", None
    if ctype not in settings.ATTACHMENT_ALLOWED_MIME or len(data) > settings.ATTACHMENT_MAX_BYTES:
        status = "rejected"
    else:
        try:
            from apps.core.storage import safe_name, upload
            path = upload("email-attachments", f"{tenant_id}/{mailbox_id}/{message_id}/{safe_name(a['filename'])}", data, ctype)
        except BusinessError:
            status = "rejected"
    fetch_one("""INSERT INTO public.email_message_attachments (tenant_id, message_id, filename, mime_type, size_bytes, storage_path, verification_status, sha256)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
              [tenant_id, message_id, a["filename"][:250], ctype, len(data), path or f"rejected:{sha}", status, sha])


def ingest(mailbox_id: str, p: dict, *, provider_message_id: str | None = None, provider_thread_id: str | None = None) -> dict:
    """Idempotent ingestion of an inbound message (already authenticated by the caller)."""
    mb = _mailbox(mailbox_id)
    tid = str(mb["tenant_id"])
    if fetch_one("SELECT 1 FROM public.email_messages WHERE tenant_id = %s AND mailbox_id = %s AND message_id_header = %s", [tid, mailbox_id, p["message_id"]]):
        return {"status": "duplicate"}
    with transaction.atomic():
        conv = _find_thread(tid, mailbox_id, p, provider_thread_id)
        prospect = campaign = None
        if conv:
            prospect, campaign = fetch_one("SELECT prospect_id, campaign_id FROM public.email_conversations WHERE id = %s", [conv])
        else:
            matches = fetch_all_dict("""SELECT DISTINCT p.id FROM public.prospect_contacts c JOIN public.prospects p ON p.id = c.prospect_id
                                         WHERE c.tenant_id = %s AND lower(c.email) = %s AND c.deleted_at IS NULL""", [tid, p["from"]])
            prospect = matches[0]["id"] if len(matches) == 1 else None
            conv = str(fetch_one("""INSERT INTO public.email_conversations (tenant_id, mailbox_id, thread_id, subject, prospect_id, labels)
                                    VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                                 [tid, mailbox_id, provider_thread_id or p["message_id"], p["subject"][:500], prospect,
                                  ["needs_review"] if len(matches) > 1 else []])[0])
        mid = str(fetch_one("""INSERT INTO public.email_messages (tenant_id, conversation_id, mailbox_id, message_id_header, in_reply_to, references_header,
                                 provider_message_id, provider_thread_id, direction, from_email, to_emails, cc_emails, subject, body_text, received_at,
                                 prospect_id, campaign_id, status, headers)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'inbound',%s,%s,%s,%s,%s, now(),%s,%s,'received',%s::jsonb) RETURNING id""",
                            [tid, conv, mailbox_id, p["message_id"], p.get("in_reply_to"), p.get("references"), provider_message_id, provider_thread_id,
                             p["from"], p.get("to") or [], p.get("cc") or [], p["subject"][:998], (p.get("text") or "")[:200000], prospect, campaign,
                             json.dumps(p.get("headers") or {})])[0])
        fetch_one("""INSERT INTO public.email_conversation_participants (tenant_id, conversation_id, email, role)
                     SELECT %s, %s, %s, 'from' WHERE NOT EXISTS (SELECT 1 FROM public.email_conversation_participants WHERE conversation_id = %s AND email = %s)
                     RETURNING id""", [tid, conv, p["from"], conv, p["from"]])
        fetch_one("""UPDATE public.email_conversations SET is_unread = true, last_inbound_at = now(), last_message_at = now(),
                       labels = (SELECT array_agg(DISTINCT l) FROM unnest(coalesce(labels,'{}') || ARRAY['inbox']) l) WHERE id = %s RETURNING 1""", [conv])
        for a in p.get("attachments") or []:
            _store_attachment(tid, mailbox_id, mid, a)
        if prospect:
            fetch_one("UPDATE public.prospects SET last_activity_at = now() WHERE id = %s RETURNING 1", [prospect])
            fetch_one("""UPDATE public.prospect_campaign_recipients r SET status = 'replied' FROM public.prospect_contacts c
                          WHERE r.contact_id = c.id AND c.prospect_id = %s AND r.status IN ('pending','active') RETURNING 1""", [prospect])
            fetch_one("""INSERT INTO public.crm_activities (tenant_id, prospect_id, activity_type, summary, channel, actor_type, entity_ref)
                         VALUES (%s,%s,'email',%s,'email','prospect',%s::jsonb) RETURNING id""",
                      [tid, prospect, f"Réponse reçue : {p['subject']}"[:500], json.dumps({"email_message_id": mid})])
    record_activity("email.received", "email_center", entity_type="email_messages", entity_id=mid, description=p["subject"][:200], tenant_id=tid)
    from .tasks import classify_task
    transaction.on_commit(lambda: classify_task.delay_traced(mid))
    return {"status": "stored", "message_id": mid, "conversation_id": conv}


# ───────────────────────────── Classification & drafts ─────────────────────────────
def rule_classify(p_text: str, subject: str, headers: dict, sender: str) -> str | None:
    h = {k.lower(): v.lower() for k, v in (headers or {}).items()}
    if "mailer-daemon" in sender or "postmaster@" in sender or h.get("x-failed-recipients"):
        return "automatic_reply"
    if UNSUB_RE.search(f"{subject} {p_text[:2000]}"):
        return "unsubscribe"
    if h.get("auto-submitted", "no") != "no" or "x-autoreply" in h or "x-autorespond" in h or h.get("precedence") in ("bulk", "auto_reply"):
        return "out_of_office" if OOO_RE.search(f"{subject} {p_text[:1000]}") else "automatic_reply"
    if OOO_RE.search(subject):
        return "out_of_office"
    return None


def classify(message_id: str) -> dict:
    tid = get_context().tenant_id
    m = fetch_one("""SELECT m.body_text, m.subject, m.headers, m.from_email, m.conversation_id, c.prospect_id, c.product_id, c.assigned_to, m.direction
                       FROM public.email_messages m JOIN public.email_conversations c ON c.id = m.conversation_id WHERE m.id = %s AND m.tenant_id = %s""", [message_id, tid])
    if not m or m[8] != "inbound":
        return {"status": "skipped"}
    text, subject, headers, sender, conv, prospect, product, assignee, _ = m
    cat, method, extra, cost, provider = rule_classify(text or "", subject or "", headers or {}, sender or ""), "rules", {}, None, None
    if not cat:
        try:
            r = complete("email.classify", [{"role": "user", "content": wrap_untrusted("email", f"Subject: {subject}\n\n{text}", 12000)}],
                         system=("Classify this prospect reply. Return ONLY JSON: {\"category\": one of " + json.dumps(CATEGORIES) +
                                 ", \"confidence\": 0-1, \"summary\": str, \"intents\": [str], \"questions\": [str], \"objections\": [str], \"next_action\": str}"),
                         max_tokens=600, untrusted=True, agent_code="email_classifier", prompt_version="email-classify-v1", product_id=str(product) if product else None)
            data = r.json()
            cat = data.get("category") if data.get("category") in CATEGORIES else "human_review_required"
            extra, method, cost, provider = data, "ai", r.cost_cents, r.provider
        except (AINotConfigured, BusinessError, ValueError):
            cat, extra = "human_review_required", {"summary": "AI classification unavailable"}
    with transaction.atomic():
        fetch_one("""INSERT INTO public.email_reply_classifications (tenant_id, message_id, category, confidence, model_code, summary, intents, questions,
                       objections, next_action, provider_code, cost_cents, method) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s) RETURNING id""",
                  [tid, message_id, cat, extra.get("confidence", 1 if method == "rules" else None), None, extra.get("summary"),
                   json.dumps(extra.get("intents", [])), json.dumps(extra.get("questions", [])), json.dumps(extra.get("objections", [])),
                   extra.get("next_action"), provider, cost, method])
        fetch_one("UPDATE public.email_messages SET classification = %s WHERE id = %s RETURNING 1", [cat, message_id])
        if (label := LABEL_FOR.get(cat)):
            fetch_one("UPDATE public.email_conversations SET labels = (SELECT array_agg(DISTINCT l) FROM unnest(coalesce(labels,'{}') || ARRAY[%s]) l) WHERE id = %s RETURNING 1",
                      [label, conv])
        if cat == "unsubscribe":  # immediate, regardless of growth mode
            fetch_one("""INSERT INTO public.prospect_suppression_lists (tenant_id, email, reason) VALUES (%s,%s,'unsubscribed')
                         ON CONFLICT (tenant_id, email) WHERE deleted_at IS NULL DO NOTHING RETURNING id""", [tid, sender])
            fetch_one("INSERT INTO public.email_suppression_events (tenant_id, email, reason, source_message_id) VALUES (%s,%s,'unsubscribe',%s) RETURNING id",
                      [tid, sender, message_id])
            fetch_one("""UPDATE public.prospect_campaign_recipients r SET status = 'unsubscribed' FROM public.prospect_contacts c
                          WHERE r.contact_id = c.id AND lower(c.email) = %s AND r.tenant_id = %s RETURNING 1""", [sender, tid])
            fetch_one("UPDATE public.prospect_contacts SET consent_status = 'opted_out' WHERE tenant_id = %s AND lower(email) = %s RETURNING 1", [tid, sender])
        if prospect and (new_status := PROSPECT_STATUS.get(cat)):
            from apps.permissions.growth import effective_mode
            if cat == "unsubscribe" or effective_mode(tid, "crm", "update_from_reply") == "automatic":
                old = fetch_one("SELECT status FROM public.prospects WHERE id = %s", [prospect])[0]
                if old != new_status:
                    fetch_one("UPDATE public.prospects SET status = %s, last_activity_at = now() WHERE id = %s RETURNING 1", [new_status, prospect])
                    fetch_one("""INSERT INTO public.crm_activities (tenant_id, prospect_id, activity_type, summary, actor_type, entity_ref)
                                 VALUES (%s,%s,'status_change',%s,'thor',%s::jsonb) RETURNING id""",
                              [tid, prospect, f"{old} → {new_status} (classification {cat})", json.dumps({"email_message_id": message_id})])
    record_audit("email.classified", "email_center", entity_type="email_messages", entity_id=message_id, after={"category": cat, "method": method})
    from apps.notifications.service import notify
    notify("email.demo_requested" if cat in ("demo_requested", "meeting_request") else "email.reply", {"subject": subject},
           users=[str(assignee)] if assignee else None, permission="email.read")
    return {"category": cat, "method": method}


def draft_reply(conversation_id: str) -> str:
    """THOR prepares a DRAFT. Product facts are the only allowed source of product/price information."""
    tid = get_context().tenant_id
    conv = fetch_one("SELECT product_id, subject FROM public.email_conversations WHERE id = %s AND tenant_id = %s", [conversation_id, tid])
    if not conv:
        raise BusinessError("conversation not found", "not_found", status_code=404)
    msgs = fetch_all_dict("""SELECT direction, from_email, subject, left(body_text, 4000) AS body FROM public.email_messages WHERE conversation_id = %s
                              ORDER BY coalesce(received_at, sent_at, created_at) DESC LIMIT 6""", [conversation_id])
    from apps.content.services import product_context
    thread = "\n\n".join(f"[{m['direction']}] {m['from_email']}: {m['body']}" for m in reversed(msgs))
    last_in = fetch_one("SELECT id FROM public.email_messages WHERE conversation_id = %s AND direction = 'inbound' ORDER BY received_at DESC LIMIT 1", [conversation_id])
    if not last_in:
        raise BusinessError("No inbound message to reply to", "invalid")
    r = complete("email.draft_reply", [{"role": "user", "content": f"Product facts (authoritative): {product_context(str(conv[0]) if conv[0] else None)}\n\n"
                                                                   + wrap_untrusted("email_thread", thread, 15000)}],
                 system=("Draft a concise, polite sales reply in the language of the last inbound message. Use ONLY the product facts given; "
                         "if a price or feature is not in the facts, say you will confirm it. Propose a next step (call/demo) when relevant. "
                         "Output only the email body."), max_tokens=700, untrusted=True, agent_code="thor", prompt_version="email-draft-v1",
                 product_id=str(conv[0]) if conv[0] else None)
    did = fetch_one("""INSERT INTO public.email_reply_drafts (tenant_id, message_id, conversation_id, author_id, body, status, generated_by, model_code)
                       VALUES (%s,%s,%s,NULL,%s,'draft','thor',%s) RETURNING id""", [tid, last_in[0], conversation_id, r.text, r.model])[0]
    fetch_one("""INSERT INTO public.crm_activities (tenant_id, prospect_id, activity_type, summary, actor_type, entity_ref)
                 SELECT %s, prospect_id, 'thor_action', 'THOR a préparé un brouillon de réponse', 'thor', %s::jsonb FROM public.email_conversations
                  WHERE id = %s AND prospect_id IS NOT NULL RETURNING id""", [tid, json.dumps({"draft_id": str(did)}), conversation_id])
    record_audit("email.draft_created", "email_center", entity_type="email_reply_drafts", entity_id=did, after={"model": r.model})
    return str(did)


FOLDERS = {
    "inbox": "c.last_inbound_at IS NOT NULL AND c.status <> 'archived'",
    "sent": "c.last_outbound_at IS NOT NULL",
    "replies": "c.last_inbound_at IS NOT NULL AND c.last_outbound_at IS NOT NULL AND c.status <> 'archived'",
    "unread": "c.is_unread",
    "interested": "'interested' = ANY(c.labels)",
    "demo_requested": "'demo_requested' = ANY(c.labels)",
    "follow_up": "'follow_up' = ANY(c.labels)",
    "drafts": "EXISTS (SELECT 1 FROM public.email_reply_drafts d WHERE d.conversation_id = c.id AND d.status = 'draft')",
    "bounced": "EXISTS (SELECT 1 FROM public.email_messages x WHERE x.conversation_id = c.id AND x.status = 'bounced')",
    "failed": "EXISTS (SELECT 1 FROM public.email_messages x WHERE x.conversation_id = c.id AND x.status = 'failed')",
    "unsubscribed": "'unsubscribed' = ANY(c.labels)",
    "archived": "c.status = 'archived'",
}


def folder(tenant_id: str, name: str, mailbox: str | None, page: int, size: int, user_id: str, only_assigned: bool) -> list[dict]:
    cond = FOLDERS.get(name, FOLDERS["inbox"])
    return fetch_all_dict(f"""
        SELECT c.id, c.subject, c.labels, c.is_unread, c.status, c.last_message_at, c.assigned_to, c.prospect_id, c.campaign_id, c.product_id,
               mb.address AS mailbox, pc.name AS campaign, pr.name AS product,
               (SELECT json_build_object('from', m.from_email, 'to', m.to_emails, 'direction', m.direction, 'classification', m.classification,
                       'snippet', left(m.body_text, 160), 'status', m.status)
                  FROM public.email_messages m WHERE m.conversation_id = c.id ORDER BY coalesce(m.received_at, m.sent_at, m.created_at) DESC LIMIT 1) AS last_message,
               (SELECT p.status FROM public.prospects p WHERE p.id = c.prospect_id) AS prospect_status
          FROM public.email_conversations c JOIN public.email_mailboxes mb ON mb.id = c.mailbox_id
          LEFT JOIN public.prospect_campaigns pc ON pc.id = c.campaign_id LEFT JOIN public.products pr ON pr.id = c.product_id
         WHERE c.tenant_id = %s AND c.deleted_at IS NULL AND ({cond}) AND (%s = '' OR c.mailbox_id::text = %s)
           AND (NOT %s OR c.assigned_to = %s)
         ORDER BY c.last_message_at DESC NULLS LAST LIMIT %s OFFSET %s""",  # noqa: S608
        [tenant_id, mailbox or "", mailbox or "", only_assigned, user_id, size, (page - 1) * size])


def timeline(conversation_id: str, tenant_id: str) -> dict:
    return {
        "messages": fetch_all_dict("""SELECT m.id, m.direction, m.from_email, m.to_emails, m.cc_emails, m.subject, m.body_text, m.status, m.classification,
                                             m.message_id_header, m.provider_message_id, m.sent_at, m.received_at, m.created_at, m.error_message,
                                             (SELECT json_agg(json_build_object('id', a.id, 'filename', a.filename, 'mime', a.mime_type, 'size', a.size_bytes,
                                                     'verification', a.verification_status)) FROM public.email_message_attachments a WHERE a.message_id = m.id) AS attachments,
                                             (SELECT row_to_json(x) FROM (SELECT category, confidence, summary, intents, questions, objections, next_action, method
                                                FROM public.email_reply_classifications k WHERE k.message_id = m.id ORDER BY created_at DESC LIMIT 1) x) AS ai
                                        FROM public.email_messages m WHERE m.conversation_id = %s AND m.tenant_id = %s
                                       ORDER BY coalesce(m.received_at, m.sent_at, m.created_at)""", [conversation_id, tenant_id]),
        "drafts": fetch_all_dict("SELECT id, body, status, generated_by, model_code, created_at FROM public.email_reply_drafts WHERE conversation_id = %s AND tenant_id = %s ORDER BY created_at DESC",
                                 [conversation_id, tenant_id]),
        "activities": fetch_all_dict("""SELECT a.activity_type, a.summary, a.actor_type, a.created_at FROM public.crm_activities a
                                         JOIN public.email_conversations c ON c.prospect_id = a.prospect_id WHERE c.id = %s AND a.tenant_id = %s ORDER BY a.created_at""",
                                     [conversation_id, tenant_id]),
    }


def report(tenant_id: str, days: int = 30) -> dict:
    row = fetch_all_dict("""
        SELECT count(*) FILTER (WHERE direction = 'outbound' AND status NOT IN ('draft','queued','failed')) AS sent,
               count(*) FILTER (WHERE direction = 'outbound' AND status IN ('accepted','delivered')) AS accepted,
               count(*) FILTER (WHERE direction = 'outbound' AND status = 'delivered') AS delivered_confirmed,
               count(*) FILTER (WHERE status = 'bounced') AS bounced, count(*) FILTER (WHERE status = 'failed') AS failed,
               count(*) FILTER (WHERE direction = 'inbound') AS replies,
               count(*) FILTER (WHERE direction = 'inbound' AND classification IN ('interested','demo_requested','meeting_request','pricing_request')) AS positive_replies,
               count(*) FILTER (WHERE classification IN ('demo_requested','meeting_request')) AS demo_requests,
               count(*) FILTER (WHERE classification = 'unsubscribe') AS unsubscribes
          FROM public.email_messages WHERE tenant_id = %s AND created_at > now() - make_interval(days => %s)""", [tenant_id, days])[0]
    rt = fetch_one("""SELECT avg(extract(epoch FROM (i.received_at - o.sent_at)) / 3600) FROM public.email_messages i
                       JOIN LATERAL (SELECT sent_at FROM public.email_messages o WHERE o.conversation_id = i.conversation_id AND o.direction = 'outbound'
                                      AND o.sent_at < i.received_at ORDER BY o.sent_at DESC LIMIT 1) o ON true
                      WHERE i.tenant_id = %s AND i.direction = 'inbound' AND i.received_at > now() - make_interval(days => %s)""", [tenant_id, days])
    by_campaign = fetch_all_dict("""SELECT c.id, c.name, count(m.*) FILTER (WHERE m.direction = 'outbound') AS sent, count(m.*) FILTER (WHERE m.direction = 'inbound') AS replies,
                                           (SELECT count(*) FROM public.prospect_campaign_recipients r JOIN public.prospect_contacts pc ON pc.id = r.contact_id
                                             JOIN public.prospects p ON p.id = pc.prospect_id WHERE r.campaign_id = c.id AND p.status = 'customer') AS converted
                                      FROM public.prospect_campaigns c LEFT JOIN public.email_messages m ON m.campaign_id = c.id
                                     WHERE c.tenant_id = %s GROUP BY c.id""", [tenant_id])
    return {**row, "avg_response_hours": round(float(rt[0]), 1) if rt and rt[0] else None, "by_campaign": by_campaign,
            "notes": {"accepted": "accepted by the provider ≠ delivered", "opens": "open tracking is indicative only and not used"}}
