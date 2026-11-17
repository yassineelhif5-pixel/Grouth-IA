"""Invitations: random token sent once by e-mail, only its SHA-256 hash is stored; expiry & revocation."""
from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context, set_context
from apps.core.db import apply_db_context, fetch_one
from apps.core.exceptions import BusinessError

from .models import TenantInvitation


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _event(invitation_id, tenant_id, event_type: str, meta: dict | None = None) -> None:
    fetch_one("""INSERT INTO public.tenant_invitation_events (tenant_id, invitation_id, event_type, actor_user_id, metadata)
                 VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id""",
              [tenant_id, invitation_id, event_type, get_context().user_id, __import__("json").dumps(meta or {})])


def create_invitation(tenant_id: str, email: str, role_code: str, message: str | None = None) -> tuple[TenantInvitation, str]:
    from apps.licensing.services import check_quota
    check_quota(tenant_id, "members.max")
    email = email.strip().lower()
    if TenantInvitation.objects.filter(tenant_id=tenant_id, email=email, status="pending", deleted_at__isnull=True).exists():
        raise BusinessError("An invitation is already pending for this e-mail", "invitation_pending", status_code=409)
    role = fetch_one("SELECT id FROM public.tenant_roles WHERE tenant_id IS NULL AND code = %s AND code <> 'tenant_owner'", [role_code])
    if not role:
        raise BusinessError("Invalid role", "invalid_role")
    token = secrets.token_urlsafe(32)
    expires = timezone.now() + timezone.timedelta(hours=settings.GROWTH["INVITATION_TTL_HOURS"])
    with transaction.atomic():
        inv = TenantInvitation.objects.create(tenant_id=tenant_id, email=email, role_id=role[0], invited_by=get_context().user_id,
                                              expires_at=expires, message=message)
        fetch_one("INSERT INTO public.invitation_tokens (invitation_id, token_hash, expires_at) VALUES (%s, %s, %s) RETURNING id",
                  [inv.id, hash_token(token), expires])
        _event(inv.id, tenant_id, "created", {"role": role_code})
        record_audit("invitation.created", "invitations", entity_type="tenant_invitations", entity_id=inv.id,
                     after={"email": email, "role": role_code, "expires_at": expires.isoformat()})
        record_activity("invitation.created", "invitations", entity_type="tenant_invitations", entity_id=inv.id,
                        description=f"Invitation envoyée à {email}")
    return inv, token  # token is returned once to be e-mailed, never stored in clear


def revoke_invitation(inv: TenantInvitation, reason: str) -> None:
    if inv.status != "pending":
        raise BusinessError("Only pending invitations can be revoked", "invalid_state")
    with transaction.atomic():
        inv.status, inv.revoked_at = "revoked", timezone.now()
        inv.save(update_fields=["status", "revoked_at"])
        _event(inv.id, inv.tenant_id, "revoked", {"reason": reason})
        record_audit("invitation.revoked", "invitations", entity_type="tenant_invitations", entity_id=inv.id, description=reason)


def accept_invitation(user, token: str) -> str:
    """Accept with the authenticated account; e-mail must match the invitation (case-insensitive)."""
    ctx = get_context()
    set_context(ctx.with_(is_platform=True, actor_type="user"))  # lookup across tenants by token hash only
    apply_db_context(get_context())
    row = fetch_one("""SELECT i.id, i.tenant_id, i.email, i.status, t.expires_at, t.used_at, i.role_id
                         FROM public.invitation_tokens t JOIN public.tenant_invitations i ON i.id = t.invitation_id
                        WHERE t.token_hash = %s""", [hash_token(token)])
    set_context(ctx)
    apply_db_context(ctx)
    if not row:
        raise BusinessError("Invalid invitation", "invalid_invitation", status_code=404)
    inv_id, tenant_id, email, status, expires_at, used_at, role_id = row
    tenant_id = str(tenant_id)
    ctx = ctx.with_(tenant_id=tenant_id)
    set_context(ctx)
    apply_db_context(ctx)
    if status != "pending" or used_at:
        raise BusinessError("Invitation already used or revoked", "invitation_closed", status_code=410)
    if expires_at < timezone.now():
        fetch_one("UPDATE public.tenant_invitations SET status = 'expired' WHERE id = %s RETURNING 1", [inv_id])
        _event(inv_id, tenant_id, "expired")
        raise BusinessError("Invitation expired", "invitation_expired", status_code=410)
    if (user.email or "").lower() != email.lower():
        record_audit("invitation.accept_denied", "invitations", entity_type="tenant_invitations", entity_id=inv_id,
                     status="denied", description="e-mail mismatch")
        raise BusinessError("This invitation was issued for another e-mail address", "email_mismatch", status_code=403)
    with transaction.atomic():
        fetch_one("""INSERT INTO public.user_profiles (id, email) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING RETURNING id""",
                  [user.id, user.email])
        member = fetch_one("""INSERT INTO public.tenant_members (tenant_id, user_id, status) VALUES (%s, %s, 'active')
                              ON CONFLICT (tenant_id, user_id) WHERE deleted_at IS NULL DO UPDATE SET status = 'active'
                              RETURNING id""", [tenant_id, user.id])[0]
        fetch_one("""INSERT INTO public.tenant_memberships (tenant_id, member_id, role_id, granted_reason)
                     VALUES (%s, %s, %s, 'invitation accepted') ON CONFLICT DO NOTHING RETURNING id""", [tenant_id, member, role_id])
        fetch_one("UPDATE public.tenant_invitations SET status = 'accepted', accepted_at = now(), accepted_user_id = %s WHERE id = %s RETURNING 1",
                  [user.id, inv_id])
        set_context(ctx.with_(is_platform=True))
        apply_db_context(get_context())
        fetch_one("UPDATE public.invitation_tokens SET used_at = now() WHERE invitation_id = %s RETURNING 1", [inv_id])
        set_context(ctx)
        apply_db_context(ctx)
        _event(inv_id, tenant_id, "accepted")
        record_audit("invitation.accepted", "invitations", entity_type="tenant_invitations", entity_id=inv_id,
                     after={"member_id": str(member)})
        record_activity("member.joined", "memberships", entity_type="tenant_members", entity_id=member,
                        description="Nouveau membre via invitation")
    return tenant_id
