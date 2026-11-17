"""Licences: plans, quotas (configurable by the PILOTE), overrides, module authorizations."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError, QuotaExceeded

from .models import SubscriptionPlan, TenantSubscription

QUOTA_SOURCES = {  # quota_code → SQL counting current usage for the tenant (%s = tenant_id)
    "products.max": "SELECT count(*) FROM public.products WHERE tenant_id = %s AND deleted_at IS NULL",
    "websites.max": "SELECT count(*) FROM public.websites WHERE tenant_id = %s AND deleted_at IS NULL",
    "members.max": "SELECT count(*) FROM public.tenant_members WHERE tenant_id = %s AND status IN ('active','invited') AND deleted_at IS NULL",
    "scheduler.configurations": "SELECT count(*) FROM public.tenant_schedulers WHERE tenant_id = %s AND deleted_at IS NULL",
    "connectors.max": "SELECT count(*) FROM public.tenant_connector_accounts WHERE tenant_id = %s AND deleted_at IS NULL AND status <> 'revoked'",
}


def effective_limit(tenant_id: str, quota_code: str) -> int | None:
    row = fetch_one(
        """SELECT coalesce(
              (SELECT (o.value->>'limit')::bigint FROM public.tenant_license_overrides o
                WHERE o.tenant_id = %s AND o.override_type = 'quota' AND o.target_code = %s AND o.deleted_at IS NULL
                  AND (o.expires_at IS NULL OR o.expires_at > now()) ORDER BY o.created_at DESC LIMIT 1),
              (SELECT q.limit_value FROM public.tenant_license_quotas q
                WHERE q.tenant_id = %s AND q.quota_code = %s AND q.deleted_at IS NULL), -1)""",
        [tenant_id, quota_code, tenant_id, quota_code])
    value = row[0] if row else -1
    return None if value is None or value < 0 else int(value)


def ensure_active_subscription(tenant_id: str) -> None:
    row = fetch_one("""SELECT status, trial_ends_at FROM public.tenant_subscriptions WHERE tenant_id = %s
                        AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1""", [tenant_id])
    if not row:
        raise BusinessError("No active subscription", "no_subscription", status_code=402)
    status, trial_end = row
    if status in ("expired", "suspended", "cancelled") or (status == "trialing" and trial_end and trial_end < timezone.now()):
        raise BusinessError("Your subscription is not active", "subscription_inactive", status_code=402)


def check_quota(tenant_id: str, quota_code: str, increment: int = 1) -> None:
    """Raise QuotaExceeded if adding `increment` would exceed the limit. None = unlimited."""
    ensure_active_subscription(tenant_id)
    limit = effective_limit(tenant_id, quota_code)
    if limit is None:
        return
    used = int(fetch_one(QUOTA_SOURCES[quota_code], [tenant_id])[0]) if quota_code in QUOTA_SOURCES else 0
    if used + increment > limit:
        record_audit("quota.exceeded", "licensing", entity_type="tenant_license_quotas", status="denied",
                     description=f"Quota {quota_code} reached ({used}/{limit})", after={"quota": quota_code, "used": used, "limit": limit})
        raise QuotaExceeded(f"Quota reached for {quota_code} ({used}/{limit})", details={"quota": quota_code, "used": used, "limit": limit})


def license_summary(tenant_id: str) -> dict:
    sub = fetch_all_dict("""SELECT s.id, s.status, s.trial_ends_at, s.current_period_end, p.code AS plan, p.name AS plan_name
                              FROM public.tenant_subscriptions s JOIN public.subscription_plans p ON p.id = s.plan_id
                             WHERE s.tenant_id = %s AND s.deleted_at IS NULL ORDER BY s.created_at DESC LIMIT 1""", [tenant_id])
    quotas = fetch_all_dict("SELECT quota_code, limit_value, period FROM public.tenant_license_quotas WHERE tenant_id = %s AND deleted_at IS NULL ORDER BY quota_code", [tenant_id])
    for q in quotas:
        q["effective_limit"] = effective_limit(tenant_id, q["quota_code"])
        sql = QUOTA_SOURCES.get(q["quota_code"])
        q["used"] = int(fetch_one(sql, [tenant_id])[0]) if sql else None
    modules = fetch_all_dict("""SELECT m.code, m.name, a.status, a.expires_at FROM public.tenant_module_authorizations a
                                  JOIN public.platform_modules m ON m.id = a.module_id
                                 WHERE a.tenant_id = %s AND a.deleted_at IS NULL ORDER BY m.sort_order""", [tenant_id])
    return {"subscription": sub[0] if sub else None, "quotas": quotas, "modules": modules}


def change_plan(tenant_id: str, plan_code: str, reason: str) -> TenantSubscription:
    """Switch plan: new subscription row, quotas/features/modules re-derived from the plan, history + audit."""
    plan = SubscriptionPlan.objects.get(code=plan_code, is_active=True)
    ctx = get_context()
    with transaction.atomic():
        prev = TenantSubscription.objects.filter(tenant_id=tenant_id, deleted_at__isnull=True).order_by("-created_at").first()
        now = timezone.now()
        trial_end = now + timezone.timedelta(hours=plan.trial_duration_hours) if plan.is_trial and plan.trial_duration_hours else None
        if prev:
            prev.status, prev.cancelled_at, prev.deleted_at = "cancelled", now, now
            prev.save(update_fields=["status", "cancelled_at", "deleted_at"])
        sub = TenantSubscription.objects.create(tenant_id=tenant_id, plan_id=plan.id, status="trialing" if trial_end else "active",
                                                current_period_start=now, trial_ends_at=trial_end, current_period_end=trial_end)
        fetch_one("""INSERT INTO public.tenant_subscription_history (tenant_id, subscription_id, event_type, from_plan_id, to_plan_id, actor_user_id, reason)
                     VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                  [tenant_id, sub.id, "created" if not prev else "upgraded", prev.plan_id if prev else None, plan.id, ctx.user_id, reason])
        # re-derive licence state from the plan (soft-delete previous rows: history is kept)
        for table in ("tenant_license_quotas", "tenant_license_feature_access"):
            fetch_one(f"UPDATE public.{table} SET deleted_at = now() WHERE tenant_id = %s AND deleted_at IS NULL RETURNING 1", [tenant_id])  # noqa: S608
        fetch_one("""INSERT INTO public.tenant_license_quotas (tenant_id, quota_code, limit_value, period, period_start, source)
                     SELECT %s, quota_code, limit_value, period, now(), 'plan' FROM public.subscription_plan_quotas WHERE plan_id = %s RETURNING 1""",
                  [tenant_id, plan.id])
        fetch_one("""INSERT INTO public.tenant_license_feature_access (tenant_id, feature_id, enabled, source)
                     SELECT %s, feature_id, enabled, 'plan' FROM public.subscription_plan_features WHERE plan_id = %s RETURNING 1""",
                  [tenant_id, plan.id])
        fetch_one("""INSERT INTO public.tenant_module_authorizations (tenant_id, module_id, status, reason, granted_by)
                     SELECT DISTINCT %s, pf.module_id, 'enabled', %s, %s FROM public.subscription_plan_features f
                       JOIN public.platform_module_features pf ON pf.id = f.feature_id WHERE f.plan_id = %s
                     ON CONFLICT DO NOTHING RETURNING 1""", [tenant_id, f"plan {plan.code}", ctx.user_id, plan.id])
        record_audit("license.plan_changed", "licensing", entity_type="tenant_subscriptions", entity_id=sub.id,
                     before={"plan_id": str(prev.plan_id)} if prev else None, after={"plan": plan.code}, description=reason,
                     tenant_id=tenant_id)
    return sub


def set_quota_override(tenant_id: str, quota_code: str, limit: int | None, reason: str, expires_at=None) -> None:
    if not reason:
        raise BusinessError("A reason is required", "reason_required")
    before = effective_limit(tenant_id, quota_code)
    fetch_one("""INSERT INTO public.tenant_license_overrides (tenant_id, override_type, target_code, value, reason, expires_at)
                 VALUES (%s, 'quota', %s, jsonb_build_object('limit', %s::bigint), %s, %s) RETURNING id""",
              [tenant_id, quota_code, -1 if limit is None else limit, reason, expires_at])
    record_audit("license.quota_overridden", "licensing", entity_type="tenant_license_overrides",
                 before={"limit": before}, after={"limit": limit, "quota": quota_code}, description=reason, tenant_id=tenant_id)


def set_module_authorization(tenant_id: str, module_code: str, status: str, reason: str) -> None:
    row = fetch_one("SELECT id FROM public.platform_modules WHERE code = %s", [module_code])
    if not row:
        raise BusinessError("Unknown module", "unknown_module", status_code=404)
    fetch_one("""INSERT INTO public.tenant_module_authorizations (tenant_id, module_id, status, reason, granted_by)
                 VALUES (%s, %s, %s, %s, %s)
                 ON CONFLICT (tenant_id, module_id) WHERE deleted_at IS NULL
                 DO UPDATE SET status = EXCLUDED.status, reason = EXCLUDED.reason, granted_by = EXCLUDED.granted_by RETURNING id""",
              [tenant_id, row[0], status, reason, get_context().user_id])
    fetch_one("""INSERT INTO public.authorization_audit_logs (tenant_id, actor_user_id, target_type, target_id, action, after_data, reason)
                 VALUES (%s, %s, 'module', %s, %s, jsonb_build_object('status', %s::text), %s) RETURNING id""",
              [tenant_id, get_context().user_id, row[0], "grant" if status == "enabled" else "suspend", status, reason])
    record_audit(f"authorization.module_{status}", "permissions", entity_type="platform_modules", entity_id=row[0],
                 after={"module": module_code, "status": status}, description=reason, tenant_id=tenant_id)
