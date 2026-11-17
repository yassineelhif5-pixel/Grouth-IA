from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.crud import AuditedTenantViewSet, tenant_serializer
from apps.core.db import fetch_all_dict
from apps.core.views import GrowthAPIView, GrowthViewSet
from rest_framework import mixins

from .models import Backlink, KeywordGroup, KeywordRanking, SeoAudit, SeoIssue, SeoKeyword, SeoProject, SeoRecommendation
from .services import compare, launch_audit


class SeoProjectViewSet(AuditedTenantViewSet):
    model, module, perm_prefix, write_suffix, required_module = SeoProject, "seo", "seo", "manage", "seo"
    serializer_class = tenant_serializer(SeoProject)
    filterset_fields = ["product", "status"]

    @action(detail=True, methods=["post"])
    def audit(self, request, pk=None):
        aid = launch_audit(str(pk), request.data.get("audit_type", "full"), request.data.get("pages_limit"), request.data.get("website_id"))
        return Response({"audit_id": aid, "status": "queued"}, status=202)


class _RO(mixins.ListModelMixin, mixins.RetrieveModelMixin, GrowthViewSet):
    required_module = "seo"
    permission_map = {"GET": "seo.read", "*": "seo.manage"}
    ordering = ["-created_at"]

    def get_queryset(self):
        return self.model.objects.filter(tenant_id=self.request.tenant.tenant_id).order_by(*self.ordering)


class SeoAuditViewSet(_RO):
    model = SeoAudit
    serializer_class = tenant_serializer(SeoAudit)
    filterset_fields = ["project", "status", "website"]

    @action(detail=True, methods=["get"])
    def pages(self, request, pk=None):
        return Response(fetch_all_dict("SELECT id, url, score, status_code, load_ms, data FROM public.seo_audit_pages WHERE audit_id = %s AND tenant_id = %s ORDER BY score",
                                       [pk, request.tenant.tenant_id]))

    @action(detail=False, methods=["get"])
    def compare(self, request):
        return Response(compare(request.query_params["from"], request.query_params["to"], request.tenant.tenant_id))


class SeoIssueViewSet(_RO, mixins.UpdateModelMixin):
    model = SeoIssue
    serializer_class = tenant_serializer(SeoIssue)
    filterset_fields = ["audit", "severity", "status", "category", "issue_code"]


class SeoRecommendationViewSet(AuditedTenantViewSet):
    model, module, perm_prefix, write_suffix, required_module = SeoRecommendation, "seo", "seo", "manage", "seo"
    serializer_class = tenant_serializer(SeoRecommendation)
    filterset_fields = ["project", "audit", "status", "priority"]
    ordering = ["priority", "-created_at"]


class SeoKeywordViewSet(AuditedTenantViewSet):
    model, module, perm_prefix, write_suffix, required_module = SeoKeyword, "seo", "seo", "manage", "seo"
    serializer_class = tenant_serializer(SeoKeyword)
    filterset_fields = ["project", "group", "is_tracked"]


class KeywordGroupViewSet(AuditedTenantViewSet):
    model, module, perm_prefix, write_suffix, required_module = KeywordGroup, "seo", "seo", "manage", "seo"
    serializer_class = tenant_serializer(KeywordGroup)


class BacklinkViewSet(AuditedTenantViewSet):
    model, module, perm_prefix, write_suffix, required_module = Backlink, "seo", "seo", "manage", "seo"
    serializer_class = tenant_serializer(Backlink)


class RankingsView(GrowthAPIView):
    permission_map = {"GET": "seo.read"}
    required_module = "seo"

    def get(self, request):
        return Response(fetch_all_dict(
            """SELECT k.keyword, r.position, r.url, r.device, r.checked_on FROM public.keyword_rankings r
                 JOIN public.seo_keywords k ON k.id = r.keyword_id WHERE r.tenant_id = %s ORDER BY r.checked_on DESC LIMIT 1000""",
            [request.tenant.tenant_id]))

_ = KeywordRanking
