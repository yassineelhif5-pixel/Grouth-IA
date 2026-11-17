import csv
import io

from django.http import HttpResponse
from django.utils import timezone
from rest_framework.response import Response

from apps.audit.services import record_access, record_audit
from apps.core.db import fetch_one
from apps.core.tenancy import has_permission
from apps.core.views import GrowthAPIView

from . import services as s


class _TenantHistory(GrowthAPIView):
    permission_map = {"GET": "history.read", "POST": "history.read"}

    def show_values(self, request) -> bool:
        return has_permission(request.tenant.tenant_id, request.user.id, "history.read_values")


class AuditEventsView(_TenantHistory):
    def get(self, request):
        return Response(s.query_audit(request.query_params, request.tenant.tenant_id, self.show_values(request)))


class ActivityView(_TenantHistory):
    def get(self, request):
        return Response(s.query_simple("activity_events", "id, created_at, user_id, product_id, event_type, module, entity_type, entity_id, description, metadata, correlation_id",
                                       s.ACTIVITY_FILTERS, request.query_params, request.tenant.tenant_id))


class ExecutionsView(_TenantHistory):
    def get(self, request):
        return Response(s.query_simple("execution_logs", "id, created_at, module, operation, execution_id, celery_task_id, status, started_at, completed_at, duration_ms, error_code, error_message, retry_count, cost_cents, correlation_id",
                                       s.EXEC_FILTERS, request.query_params, request.tenant.tenant_id))


class EntityVersionsView(_TenantHistory):
    def get(self, request, entity_type, entity_id):
        return Response(s.entity_versions(entity_type, str(entity_id), request.tenant.tenant_id, self.show_values(request)))


class CompareVersionsView(_TenantHistory):
    def get(self, request, entity_type, entity_id):
        if not self.show_values(request):
            return Response({"error": {"code": "forbidden", "message": "history.read_values required"}}, status=403)
        return Response(s.compare_versions(entity_type, str(entity_id), int(request.query_params["from"]),
                                           int(request.query_params["to"]), request.tenant.tenant_id))


class RestoreVersionView(GrowthAPIView):
    permission_map = {"POST": "tenant.settings.manage"}

    def post(self, request, entity_type, entity_id):
        obj = s.restore_version(entity_type, str(entity_id), int(request.data.get("version", 0)), request.data.get("reason", ""),
                                request.tenant.tenant_id)
        return Response({"id": str(obj.pk), "version_number": obj.version_number})


class TraceView(_TenantHistory):
    def get(self, request, correlation_id):
        return Response(s.trace(str(correlation_id), request.tenant.tenant_id))


class ExportCsvView(GrowthAPIView):
    permission_map = {"GET": "history.export"}

    def get(self, request):
        tid = request.tenant.tenant_id
        params = request.query_params.copy()
        params["page_size"] = "500"
        data = s.query_audit(params, tid, show_values=False)["results"]
        job = fetch_one("""INSERT INTO public.export_jobs (tenant_id, requested_by, export_type, scope, format, status, result)
                           VALUES (%s, %s, 'audit_events', %s::jsonb, 'csv', 'succeeded', jsonb_build_object('rows', %s::int))
                           RETURNING id""", [tid, request.user.id, __import__("json").dumps(dict(request.query_params)), len(data)])[0]
        record_access("audit_events", job, "export", reason="CSV export")
        record_audit("history.exported", "history", entity_type="export_jobs", entity_id=job, after={"rows": len(data)})
        buf = io.StringIO()
        cols = ["created_at", "actor_user_id", "actor_type", "action", "module", "entity_type", "entity_id", "description",
                "status", "correlation_id"]
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in data:
            w.writerow({k: ("'" + str(v) if str(v)[:1] in "=+-@" else v) for k, v in row.items()})  # CSV injection guard
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="growth-history-{timezone.now():%Y%m%d-%H%M}.csv"'
        return resp


# ── PILOTE (global, audited) ──
class PilotAuditView(GrowthAPIView):
    platform_scoped = True

    def get(self, request):
        return Response(s.query_audit(request.query_params, None, show_values=True))


class PilotExecutionsView(GrowthAPIView):
    platform_scoped = True

    def get(self, request):
        return Response(s.query_simple("execution_logs", "*", s.EXEC_FILTERS, request.query_params, None))


class PilotErrorsView(GrowthAPIView):
    platform_scoped = True

    def get(self, request):
        return Response(s.query_simple("system_error_events", "id, created_at, tenant_id, service_code, error_code, message, fingerprint, request_id, correlation_id",
                                       {"service": "service_code", "error_code": "error_code", "correlation_id": "correlation_id"},
                                       request.query_params, None))


class PilotTraceView(GrowthAPIView):
    platform_scoped = True

    def get(self, request, correlation_id):
        return Response(s.trace(str(correlation_id), None))
