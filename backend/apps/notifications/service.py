"""Event notifications: preferences per user/category/channel, persisted deliveries and attempts."""
from __future__ import annotations

from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one

TITLES = {"opportunity.new": "Nouvelle opportunité", "prospect.qualified": "Prospect qualifié", "email.reply": "Nouvelle réponse email",
          "email.demo_requested": "Demande de démonstration", "meeting.scheduled": "Rendez-vous programmé",
          "publication.succeeded": "Publication réussie", "publication.failed": "Publication échouée",
          "scheduler.failed": "Erreur Scheduler", "report.ready": "Rapport disponible", "quota.reached": "Quota atteint",
          "demo.expiring": "Expiration DEMO", "connector.incident": "Incident connecteur", "approval.requested": "Validation requise",
          "whatsapp.message": "Nouveau message WhatsApp"}
SEVERITY = {"publication.failed": "error", "scheduler.failed": "error", "connector.incident": "warning", "quota.reached": "warning"}


def _recipients(tenant_id: str, users: list[str] | None, permission: str | None) -> list[str]:
    if users:
        return [u for u in users if u]
    perm = permission or "reporting.read"
    rows = fetch_all_dict("""SELECT DISTINCT m.user_id FROM public.tenant_members m WHERE m.tenant_id = %s AND m.status = 'active'
                              AND m.deleted_at IS NULL AND app.has_permission(%s, m.user_id, %s)""", [tenant_id, tenant_id, perm])
    return [str(r["user_id"]) for r in rows]


def notify(event: str, payload: dict, *, users: list[str] | None = None, permission: str | None = None, link: str | None = None,
           tenant_id: str | None = None) -> int:
    tid = tenant_id or get_context().tenant_id
    if not tid:
        return 0
    title = TITLES.get(event, event)
    body = " · ".join(f"{v}" for v in payload.values() if v)[:500] or None
    sent = 0
    for uid in _recipients(tid, users, permission):
        prefs = {(r["channel"]): r["enabled"] for r in fetch_all_dict(
            """SELECT channel, enabled FROM public.notification_preferences WHERE tenant_id = %s AND user_id = %s
                AND category IN (%s, '*') AND deleted_at IS NULL""", [tid, uid, event])}
        if prefs.get("in_app", True):
            nid = fetch_one("""INSERT INTO public.notifications (tenant_id, user_id, category, title, body, link, severity)
                               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""", [tid, uid, event, title, body, link, SEVERITY.get(event, "info")])[0]
            fetch_one("""INSERT INTO public.notification_deliveries (tenant_id, notification_id, channel, status, provider)
                         VALUES (%s,%s,'in_app','delivered','growth') RETURNING id""", [tid, nid])
            sent += 1
        if prefs.get("email"):
            email = fetch_one("SELECT email FROM public.user_profiles WHERE id = %s", [uid])
            if email:
                from .tasks import deliver_email
                deliver_email(tid, uid, email[0], title, body or title, event)
    return sent
