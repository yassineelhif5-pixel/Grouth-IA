from apps.core.crud import AuditedTenantViewSet, tenant_serializer

from .models import Website, WebsitePage


class WebsiteViewSet(AuditedTenantViewSet):
    model, module, perm_prefix, quota_code, required_module = Website, "websites", "websites", "websites.max", "websites"
    serializer_class = tenant_serializer(Website)
    search_fields, filterset_fields = ["url", "name"], ["product", "status"]


class WebsitePageViewSet(AuditedTenantViewSet):
    model, module, perm_prefix, required_module = WebsitePage, "websites", "websites", "websites"
    serializer_class = tenant_serializer(WebsitePage)
    filterset_fields = ["website"]
