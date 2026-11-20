"""Base API classes: every request runs inside a verified, traced, transaction-scoped context."""
from __future__ import annotations

from django.conf import settings
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.views import APIView

from .context import set_context
from .db import apply_db_context
from .exceptions import ModuleNotAuthorized
from .tenancy import has_permission, is_platform_admin, member_license_allows, module_enabled, resolve_tenant


class GrowthContextMixin:
    """
    tenant_scoped    → X-Tenant-ID required, membership verified in DB (never trusted from the client)
    platform_scoped  → PILOTE only (platform role + MFA aal2), context flagged is_platform, actions audited
    permission_map   → {"GET": "products.read", "POST": "products.write", ...}
    required_module  → tenant must have the module authorized by its licence
    """

    tenant_scoped = True
    platform_scoped = False
    allow_without_subscription = False  # True on the views that must keep working when the trial is over (payment…)
    permission_map: dict[str, str] = {}
    required_module: str | None = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)  # authentication, DRF permissions, throttling
        user = request.user
        ctx = request.growth_ctx.with_(user_id=user.id, actor_type="user")
        set_context(ctx)
        apply_db_context(ctx)
        if self.platform_scoped:
            if not is_platform_admin(user.id):
                raise PermissionDenied("PILOTE access required")
            if settings.GROWTH["PILOT_REQUIRE_MFA"] and getattr(user, "aal", "aal1") != "aal2":
                raise PermissionDenied("MFA (aal2) required for PILOTE console")
            ctx = ctx.with_(actor_type="pilot", is_platform=True)
        elif self.tenant_scoped:
            access = resolve_tenant(user.id, request.headers.get("X-Tenant-ID"))
            request.tenant = access
            ctx = ctx.with_(tenant_id=access.tenant_id)
            perm = self.permission_map.get(request.method) or self.permission_map.get("*")
            if perm and not has_permission(access.tenant_id, user.id, perm):
                raise PermissionDenied(f"Missing permission {perm}")
            if self.required_module and not module_enabled(access.tenant_id, self.required_module):
                raise ModuleNotAuthorized(f"Module {self.required_module} is not included in your licence")
            if (self.required_module and not is_platform_admin(user.id)
                    and not member_license_allows(access.tenant_id, user.id, self.required_module)):
                raise ModuleNotAuthorized(f"Votre licence utilisateur n'inclut pas le module {self.required_module} : "
                                          "demandez à l'administrateur du tenant de vous attribuer une licence adaptée.")
        request.growth_ctx = ctx
        set_context(ctx)
        apply_db_context(ctx)
        if (self.tenant_scoped and not self.platform_scoped and not self.allow_without_subscription
                and request.method not in ("GET", "HEAD", "OPTIONS") and not is_platform_admin(user.id)):
            from apps.licensing.services import ensure_active_subscription  # late import: licensing depends on core
            ensure_active_subscription(ctx.tenant_id)  # 402 subscription_inactive → the space is read-only until payment


class GrowthAPIView(GrowthContextMixin, APIView):
    pass


class GrowthViewSet(GrowthContextMixin, viewsets.GenericViewSet):
    pass
