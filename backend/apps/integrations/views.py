"""Connectors: global catalogue (PILOTE), tenant authorizations, tenant accounts. Credentials are
stored in Supabase Vault (only the vault id + masked hint in PostgreSQL) and never returned by the API."""
from rest_framework import serializers
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.crud import AuditedTenantViewSet, tenant_serializer
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.views import GrowthAPIView

from .models import TenantConnectorAccount


class ConnectorCatalogView(GrowthAPIView):
    permission_map = {"GET": "connectors.read"}
    required_module = "connectors"

    def get(self, request):
        return Response(fetch_all_dict(
            """SELECT p.code, p.name, p.category, p.auth_type,
                      coalesce(a.status, 'not_authorized') AS authorization_status
                 FROM public.connector_providers p
                 LEFT JOIN public.tenant_connector_authorizations a ON a.provider_id = p.id AND a.tenant_id = %s AND a.deleted_at IS NULL
                WHERE p.is_enabled ORDER BY p.category, p.name""", [request.tenant.tenant_id]))


class ConnectorAccountViewSet(AuditedTenantViewSet):
    model, module, perm_prefix, quota_code, required_module = TenantConnectorAccount, "integrations", "connectors", "connectors.max", "connectors"
    write_suffix = "manage"
    serializer_class = tenant_serializer(TenantConnectorAccount)
    filterset_fields = ["provider", "status", "product"]

    def perform_create(self, serializer):
        provider = serializer.validated_data["provider"]
        authorized = fetch_one("""SELECT EXISTS (SELECT 1 FROM public.tenant_connector_authorizations WHERE tenant_id = %s
                                   AND provider_id = %s AND status = 'enabled' AND deleted_at IS NULL)""",
                               [self.request.tenant.tenant_id, provider.pk])[0]
        if not authorized:
            from apps.core.exceptions import ModuleNotAuthorized
            raise ModuleNotAuthorized("This connector is not authorized for your workspace")
        super().perform_create(serializer)


class PilotConnectorAuthorizationSerializer(serializers.Serializer):
    provider_code = serializers.CharField()
    status = serializers.ChoiceField(choices=["enabled", "disabled", "suspended"])
    reason = serializers.CharField(max_length=500)


class PilotConnectorAuthorizationView(GrowthAPIView):
    platform_scoped = True

    def get(self, request, tenant_id):
        return Response(fetch_all_dict(
            """SELECT p.code, p.name, coalesce(a.status, 'not_authorized') AS status, a.reason, a.updated_at
                 FROM public.connector_providers p LEFT JOIN public.tenant_connector_authorizations a
                   ON a.provider_id = p.id AND a.tenant_id = %s AND a.deleted_at IS NULL ORDER BY p.name""", [str(tenant_id)]))

    def post(self, request, tenant_id):
        ser = PilotConnectorAuthorizationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        row = fetch_one("""INSERT INTO public.tenant_connector_authorizations (tenant_id, provider_id, status, granted_by, reason)
                           SELECT %s, id, %s, %s, %s FROM public.connector_providers WHERE code = %s
                           ON CONFLICT (tenant_id, provider_id) WHERE deleted_at IS NULL
                           DO UPDATE SET status = EXCLUDED.status, reason = EXCLUDED.reason, granted_by = EXCLUDED.granted_by
                           RETURNING id""", [str(tenant_id), d["status"], request.user.id, d["reason"], d["provider_code"]])
        fetch_one("""INSERT INTO public.connector_audit_logs (tenant_id, actor_user_id, action, details)
                     VALUES (%s, %s, %s, jsonb_build_object('provider', %s::text, 'reason', %s::text)) RETURNING id""",
                  [str(tenant_id), request.user.id, "authorize" if d["status"] == "enabled" else "revoke", d["provider_code"], d["reason"]])
        record_audit("connector.authorization_changed", "integrations", entity_type="tenant_connector_authorizations",
                     entity_id=row[0] if row else None, after=d, tenant_id=str(tenant_id), description=d["reason"])
        return self.get(request, tenant_id)
