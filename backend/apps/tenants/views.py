from django.db.models import Count, Q
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.services import audited_create, audited_update
from apps.core.views import GrowthAPIView, GrowthViewSet

from .models import Tenant, TenantSetting
from .serializers import PilotTenantCreateSerializer, ReasonSerializer, TenantSerializer, TenantSettingSerializer
from .services import pilot_create_tenant, set_tenant_status


class CurrentTenantView(GrowthAPIView):
    permission_map = {"GET": "tenant.settings.read", "PATCH": "tenant.settings.manage"}

    def get(self, request):
        return Response(TenantSerializer(Tenant.objects.get(id=request.tenant.tenant_id)).data)

    def patch(self, request):
        tenant = Tenant.objects.select_for_update().get(id=request.tenant.tenant_id)
        ser = TenantSerializer(tenant, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        audited_update(tenant, ser.validated_data, action="tenant.updated", module="tenants",
                       expected_version=request.data.get("version_number"))
        return Response(TenantSerializer(tenant).data)


class TenantSettingViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, GrowthViewSet):
    serializer_class = TenantSettingSerializer
    permission_map = {"GET": "tenant.settings.read", "*": "tenant.settings.manage"}

    def get_queryset(self):
        return TenantSetting.objects.filter(tenant_id=self.request.tenant.tenant_id, deleted_at__isnull=True)

    def perform_create(self, serializer):
        serializer.instance = audited_create(TenantSetting, serializer.validated_data, action="tenant.setting.created",
                                             module="tenants")

    def perform_update(self, serializer):
        audited_update(serializer.instance, serializer.validated_data, action="tenant.setting.updated", module="tenants",
                       expected_version=self.request.data.get("version_number"))


class PilotTenantViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, GrowthViewSet):
    """PILOTE console — every action is audited (platform scope)."""

    platform_scoped = True
    serializer_class = TenantSerializer
    search_fields = ["name", "slug"]
    filterset_fields = ["status", "is_demo"]
    ordering_fields = ["created_at", "name"]

    def get_queryset(self):
        return Tenant.objects.filter(deleted_at__isnull=True).order_by("-created_at")

    def create(self, request):
        ser = PilotTenantCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        tenant = pilot_create_tenant(d["name"], d["slug"], str(d["owner_user_id"]) if d.get("owner_user_id") else None,
                                     d["plan_code"])
        return Response(TenantSerializer(tenant).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        ser = ReasonSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(TenantSerializer(set_tenant_status(self.get_object(), "suspended", ser.validated_data["reason"])).data)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        ser = ReasonSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(TenantSerializer(set_tenant_status(self.get_object(), "active", ser.validated_data["reason"])).data)

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        record_audit("pilot.tenant.viewed", "tenants", entity_type="tenants", entity_id=obj.pk, tenant_id=str(obj.pk))
        return Response(TenantSerializer(obj).data)


class PilotOverviewView(GrowthAPIView):
    platform_scoped = True

    def get(self, request):
        agg = Tenant.objects.filter(deleted_at__isnull=True).aggregate(
            total=Count("id"), active=Count("id", filter=Q(status="active")),
            suspended=Count("id", filter=Q(status="suspended")), demo=Count("id", filter=Q(is_demo=True)))
        return Response({"tenants": agg})
