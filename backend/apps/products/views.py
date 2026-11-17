from apps.core.crud import AuditedTenantViewSet, tenant_serializer

from .models import Product, ProductCompetitor, ProductGoal


class ProductViewSet(AuditedTenantViewSet):
    model, module, perm_prefix, quota_code, required_module = Product, "products", "products", "products.max", "products"
    serializer_class = tenant_serializer(Product)
    search_fields, filterset_fields = ["name", "slug"], ["status", "category"]


class ProductGoalViewSet(AuditedTenantViewSet):
    model, module, perm_prefix, required_module = ProductGoal, "products", "products", "products"
    serializer_class = tenant_serializer(ProductGoal)
    filterset_fields = ["product", "status"]


class ProductCompetitorViewSet(AuditedTenantViewSet):
    model, module, perm_prefix, required_module = ProductCompetitor, "products", "products", "products"
    serializer_class = tenant_serializer(ProductCompetitor)
    filterset_fields = ["product"]


from rest_framework.decorators import action  # noqa: E402
from rest_framework.response import Response  # noqa: E402

from apps.core.db import fetch_one  # noqa: E402

from .onboarding import confirm_fact  # noqa: E402


class ProductOnboardingMixin:
    @action(detail=True, methods=["post"])
    def analyze(self, request, pk=None):
        from .tasks import onboarding_task
        self.get_object()
        onboarding_task.delay_traced(str(pk))
        return Response({"status": "queued"}, status=202)

    @action(detail=True, methods=["get", "post"])
    def facts(self, request, pk=None):
        self.get_object()
        if request.method == "POST":
            return Response(confirm_fact(str(pk), request.data["field"], request.data.get("value")))
        row = fetch_one("SELECT facts, last_analysis_at FROM public.product_business_context WHERE product_id = %s AND deleted_at IS NULL", [pk])
        return Response({"facts": row[0] if row else [], "last_analysis_at": row[1] if row else None})


class ProductV2ViewSet(ProductOnboardingMixin, ProductViewSet):
    pass
