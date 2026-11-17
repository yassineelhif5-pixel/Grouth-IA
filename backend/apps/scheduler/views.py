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
            """SELECT r.id, r.task_id, coalesce(t.name, sc.name) AS task_name, r.scheduler_id, r.execution_id, r.status, r.attempt, r.started_at, r.completed_at,
                      r.duration_ms, r.error_message, r.triggered_by, r.correlation_id
                 FROM public.scheduler_execution_runs r LEFT JOIN public.scheduler_tasks t ON t.id = r.task_id
                 LEFT JOIN public.tenant_schedulers sc ON sc.id = r.scheduler_id
                WHERE r.tenant_id = %s ORDER BY r.created_at DESC LIMIT 200""", [request.tenant.tenant_id]))


# ───────────── PROMPT 2: multi-scheduler & workflows ─────────────
from django.db import transaction  # noqa: E402
from rest_framework.decorators import action  # noqa: E402

from apps.core.crud import crud  # noqa: E402
from apps.core.db import fetch_one  # noqa: E402
from apps.core.exceptions import BusinessError  # noqa: E402

from . import engine  # noqa: E402
from .models import GrowthWorkflowDefinition  # noqa: E402


class SchedulerV2ViewSet(SchedulerViewSet):
    def perform_create(self, serializer):
        d = serializer.validated_data
        nxt = engine.next_run(d.get("frequency_type", "daily"), d.get("frequency_value"), d.get("timezone", "UTC"))
        serializer.validated_data["next_run_at"] = nxt
        super().perform_create(serializer)

    def perform_update(self, serializer):
        inst = serializer.instance
        d = serializer.validated_data
        if {"frequency_type", "frequency_value", "timezone", "status"} & set(d):
            d["next_run_at"] = engine.next_run(d.get("frequency_type", inst.frequency_type), d.get("frequency_value", inst.frequency_value),
                                               d.get("timezone", inst.timezone)) if d.get("status", inst.status) == "active" else None
        super().perform_update(serializer)

    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        self.get_object()
        with transaction.atomic():
            rid = engine.enqueue_run(str(pk), "manual")
        if not rid:
            raise BusinessError("Scheduler is not active", "invalid_state", status_code=409)
        return Response({"run_id": rid}, status=202)

    @action(detail=True, methods=["get"])
    def runs(self, request, pk=None):
        self.get_object()
        return Response(fetch_all_dict("""SELECT r.id, r.execution_id, r.status, r.triggered_by, r.started_at, r.completed_at, r.duration_ms, r.cost_cents,
                                                 r.error_message, r.result, r.correlation_id,
                                                 (SELECT json_agg(json_build_object('step', s.step_name, 'status', s.status, 'output', s.output_summary) ORDER BY s.created_at)
                                                    FROM public.scheduler_execution_steps s WHERE s.run_id = r.id) AS steps
                                            FROM public.scheduler_execution_runs r WHERE r.scheduler_id = %s ORDER BY r.created_at DESC LIMIT 200""", [pk]))


_W = crud(GrowthWorkflowDefinition, module="workflows", perm="workflows", write="manage", filters=["product", "status"], quota="workflows.max")


class WorkflowViewSet(_W):
    def perform_create(self, serializer):
        engine.validate_definition(serializer.validated_data.get("definition") or {})
        super().perform_create(serializer)

    def perform_update(self, serializer):
        if "definition" in serializer.validated_data:
            engine.validate_definition(serializer.validated_data["definition"])
        super().perform_update(serializer)

    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        self.get_object()
        return Response({"execution_id": engine.start_workflow(str(pk), request.data.get("input") or {}, request.user.id)}, status=202)

    @action(detail=True, methods=["get"])
    def executions(self, request, pk=None):
        self.get_object()
        return Response(fetch_all_dict("""SELECT e.id, e.workflow_execution_id, e.status, e.current_node, e.started_at, e.completed_at, e.error_message,
                                                 (SELECT json_agg(json_build_object('node', s.node_key, 'status', s.status, 'attempt', s.attempt, 'error', s.error_message,
                                                         'output', s.output_summary) ORDER BY s.created_at) FROM public.growth_workflow_execution_steps s WHERE s.execution_id = e.id) AS steps
                                            FROM public.growth_workflow_executions e WHERE e.workflow_id = %s ORDER BY e.created_at DESC LIMIT 100""", [pk]))

    @action(detail=False, methods=["post"], url_path=r"executions/(?P<eid>[^/.]+)/(?P<op>cancel|resume)")
    def control(self, request, eid=None, op=None):
        row = fetch_one("SELECT status FROM public.growth_workflow_executions WHERE id = %s AND tenant_id = %s", [eid, request.tenant.tenant_id])
        if not row:
            raise BusinessError("execution not found", "not_found", status_code=404)
        if op == "cancel":
            fetch_one("UPDATE public.growth_workflow_executions SET cancel_requested = true WHERE id = %s RETURNING 1", [eid])
            if row[0] in ("queued", "waiting_approval", "paused"):
                fetch_one("UPDATE public.growth_workflow_executions SET status = 'cancelled', completed_at = now() WHERE id = %s RETURNING 1", [eid])
        else:
            if row[0] not in ("failed", "paused"):
                raise BusinessError("Only failed or paused executions can be resumed", "invalid_state", status_code=409)
            fetch_one("UPDATE public.growth_workflow_executions SET status = 'queued', error_message = NULL WHERE id = %s RETURNING 1", [eid])
            from .tasks import advance_workflow_task
            advance_workflow_task.delay_traced(str(eid))
        from apps.audit.services import record_audit
        record_audit(f"workflow.{op}", "workflows", entity_type="growth_workflow_executions", entity_id=eid)
        return Response({"status": op})
