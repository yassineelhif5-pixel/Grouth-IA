from rest_framework.response import Response

from apps.core.db import fetch_all_dict, fetch_one
from apps.core.views import GrowthAPIView


class TenantDashboardView(GrowthAPIView):
    permission_map = {"GET": "reporting.read"}

    def get(self, request):
        tid = request.tenant.tenant_id
        counts = fetch_all_dict(
            """SELECT (SELECT count(*) FROM public.products WHERE tenant_id = %(t)s AND deleted_at IS NULL) AS products,
                      (SELECT count(*) FROM public.websites WHERE tenant_id = %(t)s AND deleted_at IS NULL) AS websites,
                      (SELECT count(*) FROM public.tenant_members WHERE tenant_id = %(t)s AND status = 'active' AND deleted_at IS NULL) AS members,
                      (SELECT count(*) FROM public.tenant_schedulers WHERE tenant_id = %(t)s AND deleted_at IS NULL) AS schedulers,
                      (SELECT count(*) FROM public.execution_logs WHERE tenant_id = %(t)s AND created_at > now() - interval '7 days') AS executions_7d,
                      (SELECT count(*) FROM public.execution_logs WHERE tenant_id = %(t)s AND status = 'failed' AND created_at > now() - interval '7 days') AS failures_7d""",
            {"t": tid})[0]
        activity = fetch_all_dict(
            """SELECT date_trunc('day', created_at)::date AS day, count(*) AS events FROM public.activity_events
                WHERE tenant_id = %s AND created_at > now() - interval '30 days' GROUP BY 1 ORDER BY 1""", [tid])
        return Response({"counts": counts, "activity_30d": activity})


class PilotUsageView(GrowthAPIView):
    platform_scoped = True

    def get(self, request):
        return Response({
            "usage_by_tenant": fetch_all_dict(
                """SELECT t.id, t.name, count(u.id) AS events, coalesce(sum(u.cost_cents), 0) AS cost_cents
                     FROM public.tenants t LEFT JOIN public.tenant_usage_events u
                       ON u.tenant_id = t.id AND u.created_at > now() - interval '30 days'
                    WHERE t.deleted_at IS NULL GROUP BY t.id ORDER BY cost_cents DESC LIMIT 200"""),
            "ai_cost_30d": fetch_one("SELECT coalesce(sum(cost_cents), 0) FROM public.ai_usage_events WHERE created_at > now() - interval '30 days'")[0],
        })


from django.http import HttpResponse  # noqa: E402

from .global_report import build_export, dashboard  # noqa: E402


class GlobalDashboardView(GrowthAPIView):
    permission_map = {"GET": "reporting.read"}

    def get(self, request):
        return Response(dashboard(int(request.query_params.get("days", 30))))


class ExportView(GrowthAPIView):
    permission_map = {"GET": "reporting.export"}

    def get(self, request, fmt):
        res = build_export(fmt if fmt in ("pdf", "xlsx", "csv") else "pdf", int(request.query_params.get("days", 30)))
        resp = HttpResponse(res["_data"], content_type=res["_ctype"])
        resp["Content-Disposition"] = f'attachment; filename="growth-ia-report.{fmt}"'
        resp["X-Export-Job"] = res["export_job_id"]
        return resp
