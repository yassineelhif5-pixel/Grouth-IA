import json

from rest_framework.response import Response

from apps.audit.services import record_access, record_audit
from apps.core.crud import crud
from apps.core.db import fetch_one
from apps.core.exceptions import BusinessError
from apps.core.views import GrowthAPIView
from apps.permissions.growth import effective_mode

from . import services as s
from .models import EmailMailbox, EmailProviderAccount

ProviderAccountViewSet = crud(EmailProviderAccount, module="email_center", perm="email", write="manage")
MailboxViewSet = crud(EmailMailbox, module="email_center", perm="email", write="manage", filters=["status", "receive_mode"])


def _conv(request, cid):
    row = fetch_one("SELECT id, mailbox_id, prospect_id FROM public.email_conversations WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL",
                    [cid, request.tenant.tenant_id])
    if not row:
        raise BusinessError("conversation not found", "not_found", status_code=404)
    return row


class FolderView(GrowthAPIView):
    permission_map = {"GET": "email.read"}
    required_module = "email_center"

    def get(self, request, folder):
        from apps.core.tenancy import has_permission
        only_assigned = not has_permission(request.tenant.tenant_id, request.user.id, "email.manage") and "sales_rep" in request.tenant.roles
        return Response(s.folder(request.tenant.tenant_id, folder, request.query_params.get("mailbox"), int(request.query_params.get("page", 1)),
                                 min(int(request.query_params.get("page_size", 50)), 200), request.user.id, only_assigned))


class ConversationView(GrowthAPIView):
    permission_map = {"GET": "email.read", "POST": "email.send"}
    required_module = "email_center"

    def get(self, request, cid):
        _conv(request, cid)
        fetch_one("UPDATE public.email_conversations SET is_unread = false WHERE id = %s RETURNING 1", [cid])
        return Response(s.timeline(str(cid), request.tenant.tenant_id))

    def post(self, request, cid):
        """action: reply | reply_all | forward | note | assign | task | meeting | archive | unread | draft | send_draft"""
        c = _conv(request, cid)
        a, d, tid = request.data.get("action"), request.data, request.tenant.tenant_id
        if a in ("reply", "reply_all"):
            last = fetch_one("""SELECT from_email, to_emails, cc_emails, subject FROM public.email_messages WHERE conversation_id = %s AND direction = 'inbound'
                                 ORDER BY received_at DESC LIMIT 1""", [cid])
            if not last:
                raise BusinessError("No inbound message to reply to", "invalid")
            mb_addr = fetch_one("SELECT address FROM public.email_mailboxes WHERE id = %s", [c[1]])[0]
            cc = [x for x in (last[1] or []) + (last[2] or []) if x != mb_addr] if a == "reply_all" else None
            subj = last[3] if (last[3] or "").lower().startswith("re:") else f"Re: {last[3]}"
            return Response({"message_id": s.send_email(str(c[1]), [last[0]], subj, d["body"], conversation_id=str(cid), cc=cc)})
        if a == "forward":
            src = fetch_one("SELECT subject, body_text FROM public.email_messages WHERE id = %s AND conversation_id = %s", [d["message_id"], cid])
            return Response({"message_id": s.send_email(str(c[1]), d["to"], f"Fwd: {src[0]}", f"{d.get('body', '')}\n\n---------- Forwarded ----------\n{src[1]}")})
        if a == "send_draft":
            dr = fetch_one("SELECT body, status FROM public.email_reply_drafts WHERE id = %s AND conversation_id = %s", [d["draft_id"], cid])
            if not dr or dr[1] != "draft":
                raise BusinessError("draft not available", "invalid_state", status_code=409)
            last = fetch_one("SELECT from_email, subject FROM public.email_messages WHERE conversation_id = %s AND direction = 'inbound' ORDER BY received_at DESC LIMIT 1", [cid])
            body = d.get("body") or dr[0]  # the human may edit the THOR draft before sending
            mid = s.send_email(str(c[1]), [last[0]], f"Re: {last[1]}", body, conversation_id=str(cid), draft_id=str(d["draft_id"]))
            record_audit("email.draft_sent", "email_center", entity_type="email_reply_drafts", entity_id=d["draft_id"],
                         after={"edited": body != dr[0], "message_id": mid})
            return Response({"message_id": mid})
        if a == "draft":
            return Response({"draft_id": s.draft_reply(str(cid))})
        if a == "note":
            fetch_one("""INSERT INTO public.crm_activities (tenant_id, prospect_id, activity_type, summary, actor_type, entity_ref)
                         VALUES (%s,%s,'note',%s,'user',%s::jsonb) RETURNING id""", [tid, c[2], d["text"][:2000], json.dumps({"conversation_id": str(cid)})])
        elif a == "assign":
            fetch_one("UPDATE public.email_conversations SET assigned_to = %s WHERE id = %s RETURNING 1", [d["user_id"], cid])
            fetch_one("INSERT INTO public.email_commercial_assignments (tenant_id, conversation_id, user_id) VALUES (%s,%s,%s) RETURNING id", [tid, cid, d["user_id"]])
        elif a == "task":
            fetch_one("INSERT INTO public.crm_tasks (tenant_id, title, assigned_to, due_at) VALUES (%s,%s,%s,%s) RETURNING id",
                      [tid, d["title"], d.get("assigned_to") or request.user.id, d.get("due_at")])
        elif a == "meeting":
            fetch_one("INSERT INTO public.crm_meetings (tenant_id, title, starts_at, ends_at, location) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                      [tid, d["title"], d["starts_at"], d.get("ends_at"), d.get("location")])
            if c[2]:
                fetch_one("UPDATE public.prospects SET status = 'meeting_scheduled', last_activity_at = now() WHERE id = %s RETURNING 1", [c[2]])
        elif a == "archive":
            fetch_one("UPDATE public.email_conversations SET status = 'archived' WHERE id = %s RETURNING 1", [cid])
        elif a == "unread":
            fetch_one("UPDATE public.email_conversations SET is_unread = true WHERE id = %s RETURNING 1", [cid])
        else:
            raise BusinessError("unknown action", "invalid")
        record_audit(f"email.conversation.{a}", "email_center", entity_type="email_conversations", entity_id=cid, after={k: v for k, v in d.items() if k != "body"})
        return Response({"status": "ok"})


class ComposeView(GrowthAPIView):
    permission_map = {"POST": "email.send"}
    required_module = "email_center"

    def post(self, request):
        d = request.data
        return Response({"message_id": s.send_email(d["mailbox_id"], d["to"], d["subject"], d["body"], prospect_id=d.get("prospect_id"),
                                                    product_id=d.get("product_id"))}, status=201)


class AttachmentView(GrowthAPIView):
    permission_map = {"GET": "email.read"}
    required_module = "email_center"

    def get(self, request, attachment_id):
        row = fetch_one("SELECT storage_path, verification_status FROM public.email_message_attachments WHERE id = %s AND tenant_id = %s", [attachment_id, request.tenant.tenant_id])
        if not row or row[1] == "rejected":
            raise BusinessError("attachment unavailable", "not_found", status_code=404)
        from apps.core.storage import signed_url
        record_access("email_message_attachments", attachment_id, "download")
        return Response({"url": signed_url(row[0], 300), "expires_in": 300})


class EmailReportView(GrowthAPIView):
    permission_map = {"GET": "email.read"}
    required_module = "email_center"

    def get(self, request):
        return Response({**s.report(request.tenant.tenant_id, int(request.query_params.get("days", 30))),
                         "auto_reply_mode": effective_mode(request.tenant.tenant_id, "email", "auto_reply")})


class SyncNowView(GrowthAPIView):
    permission_map = {"POST": "email.manage"}
    required_module = "email_center"

    def post(self, request, mailbox_id):
        from .tasks import sync_mailbox_task
        if not fetch_one("SELECT 1 FROM public.email_mailboxes WHERE id = %s AND tenant_id = %s", [mailbox_id, request.tenant.tenant_id]):
            raise BusinessError("mailbox not found", "not_found", status_code=404)
        sync_mailbox_task.delay_traced(str(mailbox_id))
        return Response({"status": "queued"}, status=202)
