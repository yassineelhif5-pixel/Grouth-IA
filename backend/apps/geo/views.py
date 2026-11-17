from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.crud import crud, read_only
from apps.core.db import fetch_all_dict
from apps.core.views import GrowthAPIView

from .models import AiSearchQuery, AiVisibilitySnapshot, BrandEntity, GeoAudit, GeoRecommendation
from .services import snapshot

_Q = crud(AiSearchQuery, module="geo", perm="geo", write="manage", filters=["product"], search=["query"])


class QueryViewSet(_Q):
    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        from .tasks import run_query_task
        self.get_object()
        run_query_task.delay_traced(str(pk))
        return Response({"status": "queued"}, status=202)


BrandViewSet = crud(BrandEntity, module="geo", perm="geo", write="manage", filters=["product", "entity_type"])
RecommendationViewSet = crud(GeoRecommendation, module="geo", perm="geo", write="manage", filters=["product", "status"])
AuditViewSet = read_only(GeoAudit, perm="geo", required_module="geo", filters=["product", "status"])
SnapshotViewSet = read_only(AiVisibilitySnapshot, perm="geo", required_module="geo", filters=["product"])


class GeoActionsView(GrowthAPIView):
    permission_map = {"GET": "geo.read", "POST": "geo.manage"}
    required_module = "geo"

    def post(self, request, product_id):
        from .tasks import geo_audit_task
        geo_audit_task.delay_traced(str(product_id))
        return Response({"status": "queued"}, status=202)

    def get(self, request, product_id):
        """Observed responses, mentions and citations (history, filterable by engine/date)."""
        rows = fetch_all_dict(
            """SELECT r.id AS run_id, r.created_at, r.engine, r.provider_code, r.model_code, r.method, r.status, r.cost_cents, r.error_message,
                      q.query, s.response_text,
                      (SELECT json_agg(json_build_object('brand', m.mention_text, 'position', m.position)) FROM public.ai_search_mentions m WHERE m.response_id = s.id) AS mentions,
                      (SELECT json_agg(json_build_object('url', c.url, 'domain', c.domain)) FROM public.ai_search_citations c WHERE c.response_id = s.id) AS citations
                 FROM public.ai_search_runs r JOIN public.ai_search_queries q ON q.id = r.query_id
                 LEFT JOIN public.ai_search_responses s ON s.run_id = r.id
                WHERE q.product_id = %s AND r.tenant_id = %s AND (%s = '' OR r.engine = %s)
                ORDER BY r.created_at DESC LIMIT 200""",
            [product_id, request.tenant.tenant_id, request.query_params.get("engine", ""), request.query_params.get("engine", "")])
        return Response({"visibility": snapshot(str(product_id), persist=False), "observations": rows})
