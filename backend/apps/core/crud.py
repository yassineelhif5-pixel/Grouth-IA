"""Generic tenant-scoped, audited CRUD viewset (soft delete, optimistic versioning, quotas, modules)."""
from __future__ import annotations

from rest_framework import mixins, serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from .services import audited_create, audited_restore, audited_soft_delete, audited_update
from .views import GrowthViewSet

READ_ONLY = ["id", "tenant", "created_at", "updated_at", "created_by", "updated_by", "deleted_at", "version_number",
             "correlation_id"]


def tenant_serializer(model_cls, exclude_secret: bool = True):
    secret = tuple(getattr(model_cls, "SECRET_FIELDS", ()))

    class _S(serializers.ModelSerializer):
        class Meta:
            model = model_cls
            exclude = ("tenant",) + (secret if exclude_secret else ())
            read_only_fields = [f for f in READ_ONLY if f != "tenant" and f in {x.name for x in model_cls._meta.fields}]

    _S.__name__ = f"{model_cls.__name__}Serializer"
    return _S


class AuditedTenantViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                           mixins.UpdateModelMixin, mixins.DestroyModelMixin, GrowthViewSet):
    model = None
    module = "core"
    perm_prefix = "core"
    quota_code: str | None = None
    write_suffix = "write"
    ordering = ["-created_at"]

    @property
    def permission_map(self):  # type: ignore[override]
        w = f"{self.perm_prefix}.{self.write_suffix}"
        return {"GET": f"{self.perm_prefix}.read", "POST": w, "PUT": w, "PATCH": w, "DELETE": w}

    def get_queryset(self):
        qs = self.model.objects.filter(tenant_id=self.request.tenant.tenant_id)
        if self.request.query_params.get("include_deleted") != "true":
            qs = qs.filter(deleted_at__isnull=True)
        return qs.order_by(*self.ordering)

    def _entity(self) -> str:
        return self.model._meta.db_table

    def perform_create(self, serializer):
        if self.quota_code:
            from apps.licensing.services import check_quota
            check_quota(self.request.tenant.tenant_id, self.quota_code)
        serializer.instance = audited_create(self.model, serializer.validated_data, action=f"{self._entity()}.created",
                                             module=self.module, reason=self.request.data.get("change_reason"))

    def perform_update(self, serializer):
        obj = self.model.objects.select_for_update().get(pk=serializer.instance.pk)
        serializer.instance = audited_update(obj, serializer.validated_data, action=f"{self._entity()}.updated", module=self.module,
                                             expected_version=self.request.data.get("version_number"),
                                             reason=self.request.data.get("change_reason"))

    def perform_destroy(self, instance):
        reason = self.request.data.get("reason") or self.request.query_params.get("reason") or ""
        audited_soft_delete(instance, action=f"{self._entity()}.deleted", module=self.module, reason=reason)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        obj = self.model.objects.select_for_update().get(pk=pk, tenant_id=request.tenant.tenant_id)
        audited_restore(obj, action=f"{self._entity()}.restored", module=self.module, reason=request.data.get("reason", "restore"))
        return Response(self.get_serializer(obj).data)


def crud(model_cls, *, module: str, perm: str, write: str = "write", required_module: str | None = None,
         filters: list[str] | None = None, search: list[str] | None = None, quota: str | None = None, ordering: list[str] | None = None):
    """Factory for audited tenant CRUD viewsets (history, audit, activity, soft delete, quotas, permissions)."""
    attrs = {"model": model_cls, "module": module, "perm_prefix": perm, "write_suffix": write, "required_module": required_module or module,
             "serializer_class": tenant_serializer(model_cls), "filterset_fields": filters or [], "search_fields": search or [],
             "quota_code": quota, "ordering": ordering or ["-created_at"]}
    return type(f"{model_cls.__name__}ViewSet", (AuditedTenantViewSet,), attrs)


def read_only(model_cls, *, perm: str, required_module: str, filters: list[str] | None = None, ordering: list[str] | None = None):
    from rest_framework import mixins as m

    def get_queryset(self):
        return self.model.objects.filter(tenant_id=self.request.tenant.tenant_id).order_by(*self.ordering)

    attrs = {"model": model_cls, "permission_map": {"GET": f"{perm}.read"}, "required_module": required_module,
             "serializer_class": tenant_serializer(model_cls), "filterset_fields": filters or [], "ordering": ordering or ["-created_at"],
             "get_queryset": get_queryset}
    return type(f"{model_cls.__name__}ReadViewSet", (m.ListModelMixin, m.RetrieveModelMixin, GrowthViewSet), attrs)
