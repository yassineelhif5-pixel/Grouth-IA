from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.db import fetch_all_dict
from apps.core.views import GrowthAPIView

from .services import latest_status, run_checks


class HealthOverviewView(GrowthAPIView):
    platform_scoped = True

    def get(self, request):
        items = latest_status()
        order = ["down", "degraded", "not_configured", "unknown", "checking", "healthy"]
        worst = min((i["status"] or "unknown" for i in items), key=lambda s: order.index(s) if s in order else 3, default="unknown")
        return Response({"overall": worst, "checks": items})


class HealthRunView(GrowthAPIView):
    platform_scoped = True

    def post(self, request):
        codes = request.data.get("codes") or None
        results = run_checks(codes)
        record_audit("system_health.run", "system_health", after={"codes": codes or "all", "results": len(results)})
        return Response({"results": results})


class HealthHistoryView(GrowthAPIView):
    platform_scoped = True

    def get(self, request, code):
        return Response(fetch_all_dict(
            """SELECT r.status, r.latency_ms, r.error_message, r.created_at FROM public.system_health_results r
                 JOIN public.system_health_checks c ON c.id = r.check_id WHERE c.code = %s ORDER BY r.created_at DESC LIMIT 200""",
            [code]))


class IncidentsView(GrowthAPIView):
    platform_scoped = True

    def get(self, request):
        return Response(fetch_all_dict("SELECT * FROM public.system_incidents WHERE deleted_at IS NULL ORDER BY started_at DESC LIMIT 200"))
