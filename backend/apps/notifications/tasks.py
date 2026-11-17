"""Notifications: persisted first (notifications / deliveries / attempts), then delivered.
E-mail uses Django's SMTP backend configured by EMAIL_* variables; when not configured the delivery is
recorded as failed with reason not_configured (never silently dropped)."""
from __future__ import annotations

from django.conf import settings
from django.core.mail import send_mail

from apps.core.db import fetch_all_dict, fetch_one
from apps.observability.tasks_base import TracedTask, run_in_platform_scope
from config.celery import app


def _email_configured() -> bool:
    return bool(getattr(settings, "EMAIL_HOST", "")) and settings.EMAIL_HOST != "localhost"


def deliver_email(tenant_id: str | None, user_id: str | None, to: str, subject: str, body: str, category: str) -> str:
    nid = fetch_one("""INSERT INTO public.notifications (tenant_id, user_id, category, title, body)
                       VALUES (%s, %s, %s, %s, %s) RETURNING id""", [tenant_id, user_id, category, subject, body[:500]])[0]
    did = fetch_one("""INSERT INTO public.notification_deliveries (tenant_id, notification_id, channel, status, provider)
                       VALUES (%s, %s, 'email', 'queued', 'smtp') RETURNING id""", [tenant_id, nid])[0]
    status, error = "sent", None
    if not _email_configured():
        status, error = "failed", "not_configured: EMAIL_HOST missing"
    else:
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
        except Exception as exc:  # noqa: BLE001
            status, error = "failed", str(exc)[:500]
    fetch_one("""INSERT INTO public.notification_attempts (tenant_id, delivery_id, attempt, status, error_message)
                 VALUES (%s, %s, 1, %s, %s) RETURNING id""", [tenant_id, did, status, error])
    return status


@app.task(base=TracedTask, name="notifications.send_invitation_email", module="notifications")
def send_invitation_email(invitation_id: str, token: str):
    row = fetch_all_dict("""SELECT i.email, i.tenant_id, t.name FROM public.tenant_invitations i
                              JOIN public.tenants t ON t.id = i.tenant_id WHERE i.id = %s""", [invitation_id])
    if not row:
        return {"status": "missing"}
    inv = row[0]
    link = f"{settings.GROWTH['FRONTEND_URL']}/invitations/accept?token={token}"
    body = f"Vous avez été invité(e) à rejoindre {inv['name']} sur Growth IA.\n\n{link}\n"
    status = deliver_email(str(inv["tenant_id"]), None, inv["email"], f"Invitation à rejoindre {inv['name']}", body, "invitation")
    fetch_one("""INSERT INTO public.tenant_invitation_events (tenant_id, invitation_id, event_type, metadata)
                 VALUES (%s, %s, %s, '{}'::jsonb) RETURNING id""", [inv["tenant_id"], invitation_id, "sent" if status == "sent" else "failed"])
    return {"status": status}  # the token is never part of the persisted output


@app.task(base=TracedTask, name="notifications.dispatch_scheduled", module="notifications")
def dispatch_scheduled():
    def _run():
        due = fetch_all_dict("""SELECT id, tenant_id, recipient_user_id, notification_template_code, payload
                                  FROM public.scheduled_notifications
                                 WHERE status = 'pending' AND send_at <= now() AND deleted_at IS NULL
                                 ORDER BY send_at LIMIT 200 FOR UPDATE SKIP LOCKED""")
        for n in due:
            tpl = fetch_all_dict("SELECT subject, body FROM public.notification_templates WHERE code = %s",
                                 [n["notification_template_code"]])
            title = tpl[0]["subject"] if tpl else n["notification_template_code"]
            fetch_one("""INSERT INTO public.notifications (tenant_id, user_id, category, title, body)
                         VALUES (%s, %s, 'scheduled', %s, %s) RETURNING id""",
                      [n["tenant_id"], n["recipient_user_id"], title, tpl[0]["body"] if tpl else None])
            fetch_one("UPDATE public.scheduled_notifications SET status = 'sent' WHERE id = %s RETURNING 1", [n["id"]])
        return {"dispatched": len(due)}
    return run_in_platform_scope(_run)
