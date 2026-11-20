from rest_framework import serializers
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.core.services import audited_update
from apps.core.views import GrowthAPIView

from .models import TenantMember

MEMBERS_SQL = """
SELECT m.id, m.user_id, coalesce(m.display_name, p.full_name) AS display_name, p.email, p.username, m.status, m.joined_at,
       m.last_active_at, m.version_number, array_remove(array_agg(DISTINCT r.code), NULL) AS roles,
       max(lt.code) AS license_code, max(lt.name) AS license_name
  FROM public.tenant_members m
  LEFT JOIN public.user_profiles p ON p.id = m.user_id
  LEFT JOIN public.tenant_memberships ms ON ms.member_id = m.id AND ms.deleted_at IS NULL
  LEFT JOIN public.tenant_roles r ON r.id = ms.role_id
  LEFT JOIN public.member_license_assignments la ON la.member_id = m.id AND la.status = 'active' AND la.deleted_at IS NULL
  LEFT JOIN public.license_types lt ON lt.id = la.license_type_id
 WHERE m.tenant_id = %s AND m.deleted_at IS NULL AND m.status <> 'removed'
 GROUP BY m.id, p.full_name, p.email, p.username ORDER BY m.joined_at"""

ROLE_CHOICES = ["tenant_admin", "tenant_manager", "marketing_manager", "seo_manager", "content_manager", "social_media_manager",
                "sales_manager", "sales_rep", "analyst", "tenant_member", "tenant_viewer"]


class CreateUserSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role_code = serializers.ChoiceField(choices=ROLE_CHOICES, default="tenant_member")
    license_code = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    message = serializers.CharField(required=False, allow_blank=True, max_length=1000)


def create_user(tenant_id: str, data: dict) -> dict:
    """Create a user for the tenant: invitation (role + licence) + Supabase e-mail when configured, else a one-time link."""
    from apps.invitations.services import create_invitation
    from apps.memberships.licenses import send_supabase_invite
    inv, token = create_invitation(tenant_id, data["email"], data["role_code"], data.get("message") or None,
                                   license_code=data.get("license_code") or None)
    accept_path = f"/invitations/accept?token={token}"
    email_status = send_supabase_invite(inv.email, accept_path)
    body = {"invitation_id": str(inv.id), "email": inv.email, "status": inv.status, "expires_at": inv.expires_at,
            "email_status": email_status}
    if email_status != "sent":
        body["accept_path"] = accept_path  # shown once to the creator, never stored in clear
    return body


class MemberListView(GrowthAPIView):
    permission_map = {"GET": "members.read", "POST": "members.manage"}

    def get(self, request):
        return Response(fetch_all_dict(MEMBERS_SQL, [request.tenant.tenant_id]))

    def post(self, request):
        ser = CreateUserSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(create_user(request.tenant.tenant_id, ser.validated_data), status=201)


class LicensesView(GrowthAPIView):
    """Licences available for the tenant (declared by the PILOTE) with usage."""

    permission_map = {"GET": "members.read"}

    def get(self, request):
        from apps.memberships.licenses import allocations
        return Response(allocations(request.tenant.tenant_id))


class MemberLicenseView(GrowthAPIView):
    permission_map = {"*": "members.manage"}

    def put(self, request, member_id):
        from apps.memberships.licenses import assign_license
        assign_license(request.tenant.tenant_id, str(member_id), request.data.get("license_code") or None,
                       request.data.get("reason") or "")
        return Response(fetch_all_dict(MEMBERS_SQL, [request.tenant.tenant_id]))


class RoleSerializer(serializers.Serializer):
    role_code = serializers.ChoiceField(choices=ROLE_CHOICES)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class MemberDetailView(GrowthAPIView):
    permission_map = {"*": "members.manage"}

    def _member(self, request, member_id):
        m = TenantMember.objects.select_for_update().filter(id=member_id, tenant_id=request.tenant.tenant_id,
                                                            deleted_at__isnull=True).first()
        if not m:
            raise BusinessError("Member not found", "not_found", status_code=404)
        if fetch_one("SELECT app.has_tenant_role(%s, %s, ARRAY['tenant_owner'])", [request.tenant.tenant_id, m.user_id])[0]:
            raise BusinessError("The tenant owner cannot be modified here", "owner_protected", status_code=403)
        return m

    def put(self, request, member_id):
        """Replace the member's role (owner role is never assignable through the API)."""
        ser = RoleSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        m = self._member(request, member_id)
        tid = request.tenant.tenant_id
        before = fetch_all_dict("""SELECT r.code FROM public.tenant_memberships ms JOIN public.tenant_roles r ON r.id = ms.role_id
                                    WHERE ms.member_id = %s AND ms.deleted_at IS NULL""", [m.id])
        fetch_one("UPDATE public.tenant_memberships SET deleted_at = now() WHERE tenant_id = %s AND member_id = %s AND deleted_at IS NULL RETURNING 1", [tid, m.id])
        fetch_one("""INSERT INTO public.tenant_memberships (tenant_id, member_id, role_id, granted_reason)
                     SELECT %s, %s, id, %s FROM public.tenant_roles WHERE tenant_id IS NULL AND code = %s RETURNING id""",
                  [tid, m.id, ser.validated_data.get("reason") or "role change", ser.validated_data["role_code"]])
        record_audit("member.role_changed", "memberships", entity_type="tenant_members", entity_id=m.id,
                     before={"roles": [r["code"] for r in before]}, after={"roles": [ser.validated_data["role_code"]]},
                     description=ser.validated_data.get("reason", ""))
        return Response(fetch_all_dict(MEMBERS_SQL, [tid]))

    def delete(self, request, member_id):
        m = self._member(request, member_id)
        reason = request.data.get("reason") or request.query_params.get("reason")
        if not reason:
            raise BusinessError("A reason is required", "reason_required")
        from django.utils import timezone
        audited_update(m, {"status": "removed", "removed_at": timezone.now()}, action="member.removed", module="memberships",
                       reason=reason, description=f"Member removed: {reason}")
        return Response(status=204)


# ─────────────── PILOTE: users and licences of any tenant ───────────────
class PilotTenantScopeMixin:
    platform_scoped = True

    def scope(self, tenant_id):
        """Run the rest of the request inside the target tenant (platform actor, audited as pilot)."""
        from apps.core.context import get_context, set_context
        from apps.core.db import apply_db_context
        from apps.tenants.models import Tenant
        if not Tenant.objects.filter(id=tenant_id, deleted_at__isnull=True).exists():
            raise BusinessError("Tenant introuvable", "not_found", status_code=404)
        ctx = get_context().with_(tenant_id=str(tenant_id))
        set_context(ctx)
        apply_db_context(ctx)
        return str(tenant_id)


class PilotTenantMembersView(PilotTenantScopeMixin, GrowthAPIView):
    def get(self, request, tenant_id):
        return Response(fetch_all_dict(MEMBERS_SQL, [self.scope(tenant_id)]))

    def post(self, request, tenant_id):
        tid = self.scope(tenant_id)
        ser = CreateUserSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(create_user(tid, ser.validated_data), status=201)


class PilotTenantMemberView(PilotTenantScopeMixin, GrowthAPIView):
    def put(self, request, tenant_id, member_id):
        tid = self.scope(tenant_id)
        from apps.memberships.licenses import assign_license
        if "license_code" in request.data:
            assign_license(tid, str(member_id), request.data.get("license_code") or None, request.data.get("reason") or "PILOTE")
        if request.data.get("role_code"):
            ser = RoleSerializer(data=request.data)
            ser.is_valid(raise_exception=True)
            fetch_one("UPDATE public.tenant_memberships SET deleted_at = now() WHERE tenant_id = %s AND member_id = %s AND deleted_at IS NULL RETURNING 1", [tid, member_id])
            fetch_one("""INSERT INTO public.tenant_memberships (tenant_id, member_id, role_id, granted_reason)
                         SELECT %s, %s, id, 'PILOTE' FROM public.tenant_roles WHERE tenant_id IS NULL AND code = %s RETURNING id""",
                      [tid, member_id, ser.validated_data["role_code"]])
            record_audit("member.role_changed", "memberships", entity_type="tenant_members", entity_id=member_id,
                         after={"roles": [ser.validated_data["role_code"]]}, description="PILOTE")
        if request.data.get("status") in ("active", "suspended"):
            fetch_one("UPDATE public.tenant_members SET status = %s WHERE id = %s AND tenant_id = %s RETURNING 1",
                      [request.data["status"], member_id, tid])
            record_audit("member.status_changed", "memberships", entity_type="tenant_members", entity_id=member_id,
                         after={"status": request.data["status"]}, description="PILOTE")
        return Response(fetch_all_dict(MEMBERS_SQL, [tid]))


class PilotTenantLicensesView(PilotTenantScopeMixin, GrowthAPIView):
    def get(self, request, tenant_id):
        from apps.memberships.licenses import allocations
        return Response(allocations(self.scope(tenant_id)))

    def put(self, request, tenant_id):
        from apps.memberships.licenses import set_allocations
        tid = self.scope(tenant_id)
        q = request.data.get("quantities") or {}
        if not isinstance(q, dict):
            raise BusinessError("quantities doit être un objet {code: quantité}", "invalid_payload")
        return Response(set_allocations(tid, q, request.data.get("reason") or "PILOTE"))
