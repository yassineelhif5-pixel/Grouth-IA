from rest_framework.response import Response

from apps.core.crud import AuditedTenantViewSet, tenant_serializer
from apps.core.db import fetch_all_dict
from apps.core.views import GrowthAPIView

from .models import SchedulerTask, TenantScheduler


class SchedulerViewSet(AuditedTenantViewSet):
    """Scheduler configurations — DEMO licence limited to 3 (quota scheduler.configurations)."""

    model, module, perm_prefix, quota_code, required_module = TenantScheduler, "scheduler", "scheduler", "scheduler.configurations", "scheduler"
    write_suffix = "manage"
    serializer_class = tenant_serializer(TenantScheduler)
    filterset_fields = ["product", "status"]


class SchedulerTaskViewSet(AuditedTenantViewSet):
    model, module, perm_prefix, required_module = SchedulerTask, "scheduler", "scheduler", "scheduler"
    write_suffix = "manage"
    serializer_class = tenant_serializer(SchedulerTask)
    filterset_fields = ["scheduler", "status", "task_type"]


class SchedulerRunsView(GrowthAPIView):
    permission_map = {"GET": "scheduler.read"}
    required_module = "scheduler"

    def get(self, request):
        return Response(fetch_all_dict(
            """SELECT r.id, r.task_id, t.name AS task_name, r.execution_id, r.status, r.attempt, r.started_at, r.completed_at,
                      r.duration_ms, r.error_message, r.triggered_by, r.correlation_id
                 FROM public.scheduler_execution_runs r JOIN public.scheduler_tasks t ON t.id = r.task_id
                WHERE r.tenant_id = %s ORDER BY r.created_at DESC LIMIT 200""", [request.tenant.tenant_id]))
