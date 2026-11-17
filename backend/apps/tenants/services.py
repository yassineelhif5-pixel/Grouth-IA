from __future__ import annotations

from django.db import transaction

from apps.audit.services import record_audit
from apps.core.context import get_context, set_context
from apps.core.db import apply_db_context, fetch_one
from apps.core.exceptions import BusinessError
from apps.core.serialization import snapshot
from apps.core.services import audited_update

from .models import Tenant


def provision_demo_tenant(user, tenant_name: str, slug: str) -> str:
    """Transactional DEMO provisioning delegated to app.provision_demo_tenant (atomic, locked, audited)."""
    with transaction.atomic():  # savepoint: a failure leaves the request transaction usable
        row = fetch_one("SELECT app.provision_demo_tenant(%s::uuid, %s, %s)", [user.id, tenant_name, slug])
    tenant_id = str(row[0])
    ctx = get_context().with_(tenant_id=tenant_id)
    set_context(ctx)
    apply_db_context(ctx)
    return tenant_id


def pilot_create_tenant(name: str, slug: str, owner_user_id: str | None, plan_code: str) -> Tenant:
    """PILOTE creates a tenant (platform scope). Owner membership and licence are created atomically."""
    ctx = get_context()
    with transaction.atomic():
        tenant = Tenant.objects.create(name=name, slug=slug, status="active", owner_user_id=owner_user_id)
        tid = str(tenant.pk)
        set_context(ctx.with_(tenant_id=tid))
        apply_db_context(get_context())
        if owner_user_id:
            fetch_one("""WITH m AS (INSERT INTO public.tenant_members (tenant_id, user_id) VALUES (%s, %s) RETURNING id)
                         INSERT INTO public.tenant_memberships (tenant_id, member_id, role_id, granted_reason)
                         SELECT %s, m.id, r.id, 'pilot created' FROM m, public.tenant_roles r
                          WHERE r.tenant_id IS NULL AND r.code = 'tenant_owner' RETURNING id""", [tid, owner_user_id, tid])
            fetch_one("INSERT INTO public.tenant_owner_registry (tenant_id, user_id, source) VALUES (%s, %s, 'pilot_created') RETURNING id",
                      [tid, owner_user_id])
        from apps.licensing.services import change_plan
        change_plan(tid, plan_code, reason="tenant created by PILOTE")
        record_audit("tenant.created", "tenants", entity_type="tenants", entity_id=tid, after=snapshot(tenant),
                     description=f"Tenant {name} created by PILOTE", tenant_id=tid)
        set_context(ctx)
        apply_db_context(ctx)
    return tenant


def set_tenant_status(tenant: Tenant, status: str, reason: str) -> Tenant:
    if not reason:
        raise BusinessError("A reason is required", "reason_required")
    changes = {"status": status}
    if status == "suspended":
        from django.utils import timezone
        changes |= {"suspended_reason": reason, "suspended_at": timezone.now()}
    return audited_update(tenant, changes, action=f"tenant.{status}", module="tenants", reason=reason,
                          description=f"Tenant status → {status}: {reason}")
