from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.core.views import GrowthAPIView

from .growth import decide


class ApprovalsView(GrowthAPIView):
    permission_map = {"GET": "approvals.decide"}

    def get(self, request):
        status = request.query_params.get("status", "pending")
        return Response(fetch_all_dict("""SELECT * FROM public.approval_requests WHERE tenant_id = %s AND status = %s
                                          ORDER BY created_at DESC LIMIT 200""", [request.tenant.tenant_id, status]))


class ApprovalDecisionView(GrowthAPIView):
    permission_map = {"POST": "approvals.decide"}

    def post(self, request, approval_id):
        return Response(decide(str(approval_id), bool(request.data.get("approve")), request.data.get("reason") or ""))


class GrowthPoliciesView(GrowthAPIView):
    permission_map = {"GET": "tenant.settings.read", "POST": "tenant.settings.manage"}

    def get(self, request):
        return Response(fetch_all_dict(
            """SELECT c.module_code, c.action_code, c.description, c.max_mode, coalesce(p.mode, 'approval') AS mode, p.growth_mode
                 FROM public.platform_action_capabilities c LEFT JOIN public.tenant_growth_policies p
                   ON p.module_code = c.module_code AND p.action_code = c.action_code AND p.tenant_id = %s AND p.deleted_at IS NULL
                ORDER BY c.module_code, c.action_code""", [request.tenant.tenant_id]))

    def post(self, request):
        m, a, mode = request.data.get("module_code"), request.data.get("action_code"), request.data.get("mode")
        if mode not in ("automatic", "approval", "analysis", "disabled"):
            raise BusinessError("invalid mode", "invalid")
        fetch_one("""INSERT INTO public.tenant_growth_policies (tenant_id, module_code, action_code, mode, growth_mode)
                     VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tenant_id, module_code, action_code) WHERE deleted_at IS NULL
                     DO UPDATE SET mode = EXCLUDED.mode, growth_mode = EXCLUDED.growth_mode RETURNING id""",
                  [request.tenant.tenant_id, m, a, mode, request.data.get("growth_mode", "hybrid")])
        record_audit("growth_policy.updated", "permissions", after={"module": m, "action": a, "mode": mode})
        return self.get(request)


class PilotCapabilitiesView(GrowthAPIView):
    platform_scoped = True

    def post(self, request):
        fetch_one("""UPDATE public.platform_action_capabilities SET max_mode = %s WHERE module_code = %s AND action_code = %s RETURNING 1""",
                  [request.data["max_mode"], request.data["module_code"], request.data["action_code"]])
        record_audit("pilot.capability_updated", "permissions", after=dict(request.data))
        return Response({"status": "ok"})


class PilotAgentSuspensionView(GrowthAPIView):
    """Suspend / resume a module or an AI agent for ONE tenant without affecting others."""
    platform_scoped = True

    def post(self, request, tenant_id):
        kind, code, suspend = request.data.get("kind"), request.data.get("code"), bool(request.data.get("suspend", True))
        reason = request.data.get("reason") or ""
        if not reason:
            raise BusinessError("reason required", "reason_required")
        if kind == "agent":
            agent = fetch_one("SELECT id FROM public.ai_agents_registry WHERE code = %s", [code])
            if not agent:
                raise BusinessError("unknown agent", "not_found", status_code=404)
            fetch_one("""INSERT INTO public.tenant_ai_agent_authorizations (tenant_id, agent_id, status, granted_by, reason)
                         VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tenant_id, agent_id) WHERE deleted_at IS NULL
                         DO UPDATE SET status = EXCLUDED.status, reason = EXCLUDED.reason RETURNING id""",
                      [str(tenant_id), agent[0], "suspended" if suspend else "enabled", request.user.id, reason])
            if suspend:
                fetch_one("""INSERT INTO public.tenant_agent_suspensions (tenant_id, agent_id, suspended_by, reason) VALUES (%s,%s,%s,%s) RETURNING id""",
                          [str(tenant_id), agent[0], request.user.id, reason])
        else:
            from apps.licensing.services import set_module_authorization
            set_module_authorization(str(tenant_id), code, "suspended" if suspend else "enabled", reason)
        record_audit(f"pilot.{kind}.{'suspended' if suspend else 'resumed'}", "permissions", after={"code": code},
                     tenant_id=str(tenant_id), description=reason)
        return Response({"status": "suspended" if suspend else "enabled"})
