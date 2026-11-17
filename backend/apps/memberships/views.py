from rest_framework import serializers
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.core.services import audited_update
from apps.core.views import GrowthAPIView

from .models import TenantMember

MEMBERS_SQL = """
SELECT m.id, m.user_id, coalesce(m.display_name, p.full_name) AS display_name, p.email, m.status, m.joined_at,
       m.last_active_at, m.version_number, array_remove(array_agg(r.code), NULL) AS roles
  FROM public.tenant_members m
  LEFT JOIN public.user_profiles p ON p.id = m.user_id
  LEFT JOIN public.tenant_memberships ms ON ms.member_id = m.id AND ms.deleted_at IS NULL
  LEFT JOIN public.tenant_roles r ON r.id = ms.role_id
 WHERE m.tenant_id = %s AND m.deleted_at IS NULL
 GROUP BY m.id, p.full_name, p.email ORDER BY m.joined_at"""


class MemberListView(GrowthAPIView):
    permission_map = {"GET": "members.read"}

    def get(self, request):
        return Response(fetch_all_dict(MEMBERS_SQL, [request.tenant.tenant_id]))


class RoleSerializer(serializers.Serializer):
    role_code = serializers.ChoiceField(choices=["tenant_admin", "tenant_manager", "marketing_manager", "seo_manager", "content_manager", "social_media_manager", "sales_manager", "sales_rep", "analyst", "tenant_member", "tenant_viewer"])
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
