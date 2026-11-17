from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response

from apps.audit.services import record_activity, record_audit
from apps.core.db import fetch_all_dict
from apps.core.exceptions import BusinessError
from apps.core.permissions import IsVerifiedUser
from apps.core.services import audited_update
from apps.core.tenancy import is_platform_admin
from apps.core.views import GrowthAPIView
from apps.tenants.services import provision_demo_tenant

from .models import UserProfile
from .serializers import DemoSignupSerializer, UserProfileSerializer


class MeView(GrowthAPIView):
    """Current user: profile, tenants, roles, effective permissions and authorized modules."""

    tenant_scoped = False

    def get(self, request):
        uid = request.user.id
        profile = UserProfile.objects.filter(id=uid).first()
        tenants = fetch_all_dict(
            """SELECT t.id, t.name, t.slug, t.status, t.is_demo,
                      array_remove(array_agg(DISTINCT r.code), NULL) AS roles,
                      (SELECT array_agg(DISTINCT p.code) FROM public.permissions p
                        WHERE p.scope = 'tenant' AND app.has_permission(t.id, %s::uuid, p.code)) AS permissions,
                      (SELECT array_agg(m.code ORDER BY m.sort_order) FROM public.tenant_module_authorizations a
                         JOIN public.platform_modules m ON m.id = a.module_id
                        WHERE a.tenant_id = t.id AND a.status = 'enabled' AND a.deleted_at IS NULL
                          AND (a.expires_at IS NULL OR a.expires_at > now())) AS modules,
                      (SELECT jsonb_build_object('plan', sp.code, 'status', s.status, 'trial_ends_at', s.trial_ends_at)
                         FROM public.tenant_subscriptions s JOIN public.subscription_plans sp ON sp.id = s.plan_id
                        WHERE s.tenant_id = t.id AND s.deleted_at IS NULL ORDER BY s.created_at DESC LIMIT 1) AS subscription
                 FROM public.tenant_members mb
                 JOIN public.tenants t ON t.id = mb.tenant_id AND t.deleted_at IS NULL
                 LEFT JOIN public.tenant_memberships ms ON ms.member_id = mb.id AND ms.deleted_at IS NULL
                 LEFT JOIN public.tenant_roles r ON r.id = ms.role_id
                WHERE mb.user_id = %s AND mb.status = 'active' AND mb.deleted_at IS NULL
                GROUP BY t.id ORDER BY t.name""", [uid, uid])
        return Response({
            "user": {"id": uid, "email": request.user.email, "email_verified": request.user.email_verified,
                     "aal": request.user.aal, "is_pilot": is_platform_admin(uid)},
            "profile": UserProfileSerializer(profile).data if profile else None,
            "tenants": tenants,
        })

    def patch(self, request):
        profile = UserProfile.objects.select_for_update().get(id=request.user.id)
        ser = UserProfileSerializer(profile, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        audited_update(profile, ser.validated_data, action="profile.updated", module="accounts",
                       expected_version=request.data.get("version_number"))
        return Response(UserProfileSerializer(profile).data)


class DemoSignupView(GrowthAPIView):
    """DEMO onboarding: verified user → tenant + Tenant Admin + 72h DEMO licence (one per user)."""

    tenant_scoped = False
    permission_classes = GrowthAPIView.permission_classes + [IsVerifiedUser]

    def post(self, request):
        ser = DemoSignupSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            tenant_id = provision_demo_tenant(request.user, ser.validated_data["tenant_name"], ser.validated_data["slug"])
        except IntegrityError as e:
            msg = str(e)
            if "already provisioned" in msg:
                raise BusinessError("A DEMO workspace already exists for this account", "demo_already_used", status_code=409) from e
            if "slug" in msg:
                raise BusinessError("This workspace identifier is already taken", "slug_taken", status_code=409) from e
            raise
        if ser.validated_data.get("full_name"):
            UserProfile.objects.filter(id=request.user.id).update(full_name=ser.validated_data["full_name"])
        record_audit("signup.demo_completed", "accounts", entity_type="tenants", entity_id=tenant_id,
                     description="DEMO signup completed", tenant_id=tenant_id)
        record_activity("signup.completed", "accounts", entity_type="tenants", entity_id=tenant_id, tenant_id=tenant_id,
                        description="Inscription DEMO terminée")
        return Response({"tenant_id": tenant_id}, status=status.HTTP_201_CREATED)
