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
