from rest_framework import serializers
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.views import GrowthAPIView

from .services import change_plan, license_summary, set_module_authorization, set_quota_override


class LicenseView(GrowthAPIView):
    permission_map = {"GET": "licenses.read"}

    def get(self, request):
        return Response(license_summary(request.tenant.tenant_id))


class LicenseRequestSerializer(serializers.Serializer):
    request_type = serializers.ChoiceField(choices=["module", "feature", "agent", "quota", "plan_upgrade"])
    target_code = serializers.CharField(max_length=120)
    message = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class LicenseRequestView(GrowthAPIView):
    permission_map = {"GET": "licenses.read", "POST": "licenses.request"}

    def get(self, request):
        return Response(fetch_all_dict("SELECT * FROM public.tenant_license_requests WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 100",
                                       [request.tenant.tenant_id]))

    def post(self, request):
        ser = LicenseRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        rid = fetch_one("""INSERT INTO public.tenant_license_requests (tenant_id, requested_by, request_type, target_code, message)
                           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                        [request.tenant.tenant_id, request.user.id, d["request_type"], d["target_code"], d.get("message")])[0]
        record_audit("license.request_created", "licensing", entity_type="tenant_license_requests", entity_id=rid, after=d)
        return Response({"id": str(rid)}, status=201)


class PilotLicenseSerializer(serializers.Serializer):
    operation = serializers.ChoiceField(choices=["change_plan", "quota_override", "module"])
    reason = serializers.CharField(max_length=500)
    plan_code = serializers.CharField(required=False)
    quota_code = serializers.CharField(required=False)
    limit = serializers.IntegerField(required=False, allow_null=True)
    module_code = serializers.CharField(required=False)
    status = serializers.ChoiceField(choices=["enabled", "disabled", "suspended"], required=False)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class PilotTenantLicenseView(GrowthAPIView):
    platform_scoped = True

    def get(self, request, tenant_id):
        return Response(license_summary(str(tenant_id)))

    def post(self, request, tenant_id):
        ser = PilotLicenseSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d, tid = ser.validated_data, str(tenant_id)
        if d["operation"] == "change_plan":
            change_plan(tid, d["plan_code"], d["reason"])
        elif d["operation"] == "quota_override":
            set_quota_override(tid, d["quota_code"], d.get("limit"), d["reason"], d.get("expires_at"))
        else:
            set_module_authorization(tid, d["module_code"], d.get("status", "enabled"), d["reason"])
        return Response(license_summary(tid))


class PilotPlanView(GrowthAPIView):
    """Plans and their quotas — limits are editable by the PILOTE."""

    platform_scoped = True

    def get(self, request):
        return Response(fetch_all_dict(
            """SELECT p.id, p.code, p.name, p.is_trial, p.trial_duration_hours, p.is_active,
                      coalesce(jsonb_object_agg(q.quota_code, q.limit_value) FILTER (WHERE q.id IS NOT NULL), '{}') AS quotas
                 FROM public.subscription_plans p LEFT JOIN public.subscription_plan_quotas q ON q.plan_id = p.id
                GROUP BY p.id ORDER BY p.sort_order"""))

    def patch(self, request):
        plan_code, quota_code, limit = request.data.get("plan_code"), request.data.get("quota_code"), request.data.get("limit")
        before = fetch_one("""SELECT q.limit_value FROM public.subscription_plan_quotas q JOIN public.subscription_plans p ON p.id = q.plan_id
                               WHERE p.code = %s AND q.quota_code = %s""", [plan_code, quota_code])
        fetch_one("""INSERT INTO public.subscription_plan_quotas (plan_id, quota_code, limit_value)
                     SELECT id, %s, %s FROM public.subscription_plans WHERE code = %s
                     ON CONFLICT (plan_id, quota_code) DO UPDATE SET limit_value = EXCLUDED.limit_value RETURNING id""",
                  [quota_code, limit, plan_code])
        record_audit("plan.quota_updated", "licensing", entity_type="subscription_plan_quotas",
                     before={"limit": before[0] if before else None}, after={"plan": plan_code, "quota": quota_code, "limit": limit},
                     description=request.data.get("reason", ""))
        return self.get(request)
