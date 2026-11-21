"""Visibility programmes API (module SEO; permissions seo.read / seo.manage, scheduler.manage for scheduling)."""
from django.http import HttpResponse
from rest_framework import mixins, serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.crud import crud, read_only
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.core.views import GrowthAPIView, GrowthViewSet

from . import services
from .models import AiVisibilityQuestion, TenantRoadmapItem, VisibilityAudit, VisibilityProfile


class ProgrammeSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    site_urls = serializers.ListField(child=serializers.CharField(max_length=500), min_length=1, max_length=5)
    competitors = serializers.ListField(child=serializers.JSONField(), required=False, max_length=10)
    scheduler_kind = serializers.ChoiceField(choices=["standard", "intelligent"], default="standard")
    scope = serializers.ListField(child=serializers.ChoiceField(choices=["seo", "geo", "prospect"]), min_length=1)
    sector = serializers.CharField(required=False, allow_blank=True, max_length=200)
    audience = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    offer = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    languages = serializers.ListField(child=serializers.CharField(max_length=10), required=False)
    countries = serializers.ListField(child=serializers.CharField(max_length=10), required=False)
    goals = serializers.ListField(child=serializers.CharField(max_length=200), required=False)
    product_id = serializers.UUIDField(required=False, allow_null=True)
    profile_id = serializers.UUIDField(required=False, allow_null=True)
    answers = serializers.DictField(required=False)


class ProgrammeView(GrowthAPIView):
    """Wizard entry point: create (or reuse) the visibility profile and launch the AI audit."""

    permission_map = {"POST": "seo.manage"}
    required_module = "seo"

    def post(self, request):
        ser = ProgrammeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        pid = str(d["profile_id"]) if d.get("profile_id") else services.create_profile(
            {**d, "product_id": str(d["product_id"]) if d.get("product_id") else None})
        aid = services.launch_audit(pid, d["scope"])
        fetch_one("UPDATE public.visibility_profiles SET goals = goals || %s::jsonb WHERE id = %s RETURNING 1",
                  [__import__("json").dumps([f"kind:{d['scheduler_kind']}"]), pid])
        return Response({"profile_id": pid, "audit_id": aid, "scheduler_kind": d["scheduler_kind"]}, status=202)


VisibilityProfileViewSet = crud(VisibilityProfile, module="visibility", perm="seo", write="manage", required_module="seo",
                                search=["name"])
AiVisibilityQuestionViewSet = crud(AiVisibilityQuestion, module="visibility", perm="geo", write="manage", required_module="geo",
                                   filters=["profile_id", "is_active"])
TenantRoadmapViewSet = crud(TenantRoadmapItem, module="visibility", perm="seo", write="manage", required_module="seo",
                            filters=["audit_id", "phase", "status", "area"])


class VisibilityAuditViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, GrowthViewSet):
    permission_map = {"GET": "seo.read", "POST": "seo.manage"}
    required_module = "seo"
    serializer_class = read_only(VisibilityAudit, perm="seo", required_module="seo").serializer_class
    filterset_fields = ["profile_id", "status", "audit_type"]

    def get_queryset(self):
        return VisibilityAudit.objects.filter(tenant_id=self.request.tenant.tenant_id).order_by("-created_at")

    @action(detail=True, methods=["get"])
    def progress(self, request, pk=None):
        row = fetch_all_dict("""SELECT id, status, progress, step, score, error, started_at, finished_at FROM public.visibility_audits
                                 WHERE id = %s AND tenant_id = %s""", [pk, request.tenant.tenant_id])
        if not row:
            raise BusinessError("Audit introuvable", "not_found", status_code=404)
        return Response(row[0])

    @action(detail=True, methods=["get"])
    def report(self, request, pk=None):
        return Response(services.audit_report(str(pk)))

    @action(detail=False, methods=["post"], url_path="tenant")
    def tenant_audit(self, request):
        """Full tenant technical audit: every visibility profile (or the first site given) + roadmap + report."""
        profiles = fetch_all_dict("SELECT id FROM public.visibility_profiles WHERE tenant_id = %s AND deleted_at IS NULL ORDER BY created_at",
                                  [request.tenant.tenant_id])
        if not profiles:
            urls = request.data.get("site_urls") or []
            if not urls:
                raise BusinessError("Ajoutez d'abord le site de votre SaaS (lien) pour lancer l'audit.", "site_url_required")
            profiles = [{"id": services.create_profile({"site_urls": urls, "name": request.data.get("name")})}]
        ids = [services.launch_audit(str(p["id"]), ["seo", "geo", "prospect"], audit_type="tenant_full") for p in profiles[:3]]
        return Response({"audit_ids": ids}, status=202)


class RecommendationViewSet(mixins.ListModelMixin, GrowthViewSet):
    permission_map = {"GET": "seo.read", "POST": "seo.manage"}
    required_module = "seo"
    filterset_fields = ["audit_id", "profile_id", "status", "category", "priority"]

    def list(self, request):
        q = request.query_params
        rows = fetch_all_dict("""SELECT id, audit_id, profile_id, category, code, title, detail, priority, impact, effort, evidence, apply_mode,
                                        channel, status, frequency, times_per_period, applied_result, applied_at, created_at
                                   FROM public.visibility_recommendations WHERE tenant_id = %s AND deleted_at IS NULL
                                    AND (%s::uuid IS NULL OR audit_id = %s::uuid) AND (%s::text IS NULL OR status = %s)
                                  ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at
                                  LIMIT 500""",
                              [request.tenant.tenant_id, q.get("audit_id"), q.get("audit_id"), q.get("status"), q.get("status")])
        return Response(rows)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        d = request.data
        return Response(services.accept_recommendation(str(pk), d.get("frequency"), d.get("times_per_period"),
                                                       d.get("scheduler_kind", "standard"), d.get("autonomy", "approval"), bool(d.get("run_now"))))

    @action(detail=True, methods=["post"], url_path="run-now")
    def run_now(self, request, pk=None):
        """Immediate execution of a validated action (on top of its programmed frequency)."""
        return Response(services.run_now(str(pk)))

    @action(detail=False, methods=["get"])
    def execution(self, request):
        """Progress of validated actions, polled by the results page."""
        return Response(services.execution_status(request.query_params.get("audit_id")))

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        services.reject_recommendation(str(pk), request.data.get("reason") or "refusé par l'utilisateur")
        return Response({"status": "rejected"})

    @action(detail=False, methods=["post"], url_path="accept-bulk")
    def accept_bulk(self, request):
        """Validate several actions at once: [{id, frequency, times_per_period}] + kind + autonomy."""
        out, errors = [], []
        kind, autonomy = request.data.get("scheduler_kind", "standard"), request.data.get("autonomy", "approval")
        run_now = bool(request.data.get("run_now"))
        for item in request.data.get("items") or []:
            try:
                out.append(services.accept_recommendation(str(item["id"]), item.get("frequency"), item.get("times_per_period"), kind, autonomy,
                                                          run_now))
            except BusinessError as e:
                errors.append({"id": item.get("id"), "code": e.code, "message": e.message})
        if kind == "intelligent" and out:
            prof = fetch_one("""SELECT p.id, p.product_id, p.name FROM public.visibility_recommendations r JOIN public.visibility_profiles p ON p.id = r.profile_id
                                 WHERE r.id = %s""", [out[0]["recommendation_id"]])
            if prof:
                try:
                    services.create_intelligent_watch(str(prof[0]), str(prof[1]), prof[2])
                except BusinessError as e:
                    errors.append({"code": e.code, "message": e.message})
        return Response({"applied": out, "errors": errors})


class AssetDownloadView(GrowthAPIView):
    permission_map = {"GET": "seo.read"}
    required_module = "seo"

    def get(self, request, asset_id):
        row = fetch_one("""SELECT filename, content, content_type FROM public.visibility_generated_assets
                            WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL""", [asset_id, request.tenant.tenant_id])
        if not row:
            raise BusinessError("Fichier introuvable", "not_found", status_code=404)
        resp = HttpResponse(row[1], content_type=f"{row[2]}; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{row[0]}"'
        return resp


class AssistantView(GrowthAPIView):
    permission_map = {"POST": "seo.read"}
    required_module = "seo"

    def post(self, request):
        return Response(services.assistant_reply(request.data.get("profile_id"), str(request.data.get("message") or "")[:4000],
                                                 request.data.get("history") or [],
                                                 request.data.get("answers") if isinstance(request.data.get("answers"), dict) else None))

    def get(self, request):
        return Response({"questions": [{"key": k, "question": q} for k, q in services.FUNDAMENTAL_QUESTIONS], "channels": services.CHANNELS})


class KpiView(GrowthAPIView):
    permission_map = {"GET": "reporting.read"}

    def get(self, request):
        return Response(services.kpis())


class AiVisibilityView(GrowthAPIView):
    permission_map = {"GET": "geo.read", "POST": "geo.manage"}
    required_module = "geo"

    def get(self, request):
        return Response(services.ai_visibility_dashboard())

    def post(self, request):
        """Build the question library for a profile, then (optionally) run the tests through the GEO engine."""
        pid = request.data.get("profile_id")
        if not pid:
            raise BusinessError("profile_id requis", "invalid_payload")
        return Response({"created": services.seed_questions(str(pid))})


class CompetitorDiscoverView(GrowthAPIView):
    """Right after the site link is entered: competitors to compare against, each with its source and evidence."""
    permission_map = {"POST": "seo.manage"}
    required_module = "seo"

    def post(self, request):
        site = (request.data.get("site_url") or "").strip()
        if "." not in site:
            raise BusinessError("Indiquez le lien du site", "invalid_url")
        return Response(services.discover_competitors(site, request.data.get("name"), request.data.get("sector")))
