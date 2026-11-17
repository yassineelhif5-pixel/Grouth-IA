from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.crud import crud
from apps.core.db import fetch_all_dict
from apps.core.exceptions import BusinessError
from apps.core.views import GrowthAPIView

from . import services as s
from .models import OpportunitySearchProject, SocialListeningConfig, SocialSignal

_P = crud(OpportunitySearchProject, module="opportunities", perm="opportunities", write="manage", filters=["product", "status"])


class HuntProjectViewSet(_P):
    @action(detail=True, methods=["post"])
    def hunt(self, request, pk=None):
        from .tasks import hunt_task
        self.get_object()
        hunt_task.delay_traced(str(pk))
        return Response({"status": "queued"}, status=202)


class OpportunityBoardView(GrowthAPIView):
    permission_map = {"GET": "opportunities.read", "POST": "opportunities.manage"}
    required_module = "opportunities"

    def get(self, request):
        kinds = [request.query_params["kind"]] if request.query_params.get("kind") in s.TABLES else list(s.TABLES)
        st, product = request.query_params.get("status", ""), request.query_params.get("product", "")
        union = " UNION ALL ".join(
            f"""SELECT '{k}' AS kind, id, title, description, status, score, confidence, potential, difficulty, recommendation, hunter, product_id,
                       detected_at, created_at, (SELECT count(*) FROM public.opportunity_evidence e WHERE e.opportunity_id = o.id) AS evidence_count
                  FROM public.{s.TABLES[k]} o WHERE tenant_id = %(t)s AND deleted_at IS NULL AND (%(s)s = '' OR status = %(s)s)
                   AND (%(p)s = '' OR product_id::text = %(p)s)""" for k in kinds)
        return Response(fetch_all_dict(f"SELECT * FROM ({union}) x ORDER BY score DESC NULLS LAST, created_at DESC LIMIT 500",  # noqa: S608
                                       {"t": request.tenant.tenant_id, "s": st, "p": product}))

    def post(self, request):
        kind = request.data.get("kind")
        if kind not in s.TABLES:
            raise BusinessError("invalid kind", "invalid")
        s.change_status(kind, request.data["id"], request.data["status"], request.data.get("reason") or "")
        return Response({"status": request.data["status"]})


class OpportunityEvidenceView(GrowthAPIView):
    permission_map = {"GET": "opportunities.read"}
    required_module = "opportunities"

    def get(self, request, opp_id):
        return Response({
            "evidence": fetch_all_dict("SELECT url, excerpt, created_at FROM public.opportunity_evidence WHERE opportunity_id = %s AND tenant_id = %s", [opp_id, request.tenant.tenant_id]),
            "scores": fetch_all_dict("""SELECT s.score, s.model_version, s.created_at, json_agg(json_build_object('factor', f.factor, 'weight', f.weight, 'value', f.value)) AS factors
                                          FROM public.opportunity_scores s LEFT JOIN public.opportunity_score_factors f ON f.score_id = s.id
                                         WHERE s.opportunity_id = %s AND s.tenant_id = %s GROUP BY s.id ORDER BY s.created_at DESC""", [opp_id, request.tenant.tenant_id]),
            "actions": fetch_all_dict("SELECT action, assigned_to, created_at FROM public.opportunity_actions WHERE opportunity_id = %s AND tenant_id = %s ORDER BY created_at DESC",
                                      [opp_id, request.tenant.tenant_id]),
        })


_L = crud(SocialListeningConfig, module="social_hunter", perm="opportunities", write="manage", filters=["product", "status"])


class ListeningViewSet(_L):
    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        from .tasks import listen_task
        self.get_object()
        listen_task.delay_traced(str(pk))
        return Response({"status": "queued"}, status=202)


_S = crud(SocialSignal, module="social_hunter", perm="opportunities", write="manage", filters=["config", "status", "intent", "source"])


class SignalViewSet(_S):
    @action(detail=True, methods=["post"])
    def to_prospect(self, request, pk=None):
        """Creates a prospect from a public signal. Consent stays 'unknown': no automatic outreach."""
        from apps.core.services import audited_create, audited_update
        from apps.prospects.models import Prospect
        sig = self.get_object()
        p = audited_create(Prospect, {"status": "new_lead", "source_detail": f"{sig.source}:{sig.url}", "need_detected": (sig.title or "")[:500],
                                      "score": sig.score, "confidence": sig.confidence}, action="prospects.created_from_signal", module="prospects")
        audited_update(sig, {"status": "converted"}, action="social_signal.converted", module="opportunities")
        return Response({"prospect_id": str(p.pk)})
