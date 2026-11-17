from rest_framework import serializers
from rest_framework.response import Response

from apps.core.db import fetch_all_dict
from apps.core.exceptions import BusinessError
from apps.core.views import GrowthAPIView

from .models import TenantInvitation
from .services import accept_invitation, create_invitation, revoke_invitation


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role_code = serializers.ChoiceField(choices=["tenant_admin", "tenant_manager", "marketing_manager", "seo_manager", "content_manager", "social_media_manager", "sales_manager", "sales_rep", "analyst", "tenant_member", "tenant_viewer"])
    message = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class InvitationListView(GrowthAPIView):
    permission_map = {"*": "invitations.manage"}

    def get(self, request):
        return Response(fetch_all_dict(
            """SELECT i.id, i.email, r.code AS role, i.status, i.expires_at, i.accepted_at, i.created_at
                 FROM public.tenant_invitations i JOIN public.tenant_roles r ON r.id = i.role_id
                WHERE i.tenant_id = %s AND i.deleted_at IS NULL ORDER BY i.created_at DESC""", [request.tenant.tenant_id]))

    def post(self, request):
        ser = InvitationCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        inv, token = create_invitation(request.tenant.tenant_id, **ser.validated_data)
        from apps.notifications.tasks import send_invitation_email
        send_invitation_email.delay_traced(str(inv.id), token)  # token travels only in the e-mail
        return Response({"id": str(inv.id), "status": inv.status, "expires_at": inv.expires_at}, status=201)


class InvitationRevokeView(GrowthAPIView):
    permission_map = {"*": "invitations.manage"}

    def post(self, request, invitation_id):
        inv = TenantInvitation.objects.select_for_update().filter(id=invitation_id, tenant_id=request.tenant.tenant_id).first()
        if not inv:
            raise BusinessError("Invitation not found", "not_found", status_code=404)
        revoke_invitation(inv, request.data.get("reason", "revoked"))
        return Response({"status": "revoked"})


class InvitationAcceptView(GrowthAPIView):
    tenant_scoped = False

    def post(self, request):
        token = str(request.data.get("token") or "")
        if len(token) < 20:
            raise BusinessError("Invalid invitation", "invalid_invitation")
        return Response({"tenant_id": accept_invitation(request.user, token)})
