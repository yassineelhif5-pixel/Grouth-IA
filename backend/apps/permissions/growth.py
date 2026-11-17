"""Growth modes (Assisted / Autonomous / Hybrid) and human validation.

effective mode = min(PILOTE maximum capability, tenant policy).  automatic > approval > analysis > disabled.
"""
from __future__ import annotations

import json

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_one
from apps.core.exceptions import BusinessError

ORDER = {"disabled": 0, "analysis": 1, "approval": 2, "automatic": 3}


def effective_mode(tenant_id: str, module: str, action: str) -> str:
    row = fetch_one("""SELECT (SELECT max_mode FROM public.platform_action_capabilities WHERE module_code = %s AND action_code = %s),
                              (SELECT mode FROM public.tenant_growth_policies WHERE tenant_id = %s AND module_code = %s
                                  AND action_code = %s AND deleted_at IS NULL)""", [module, action, tenant_id, module, action])
    cap = (row and row[0]) or "approval"
    pol = (row and row[1]) or "approval"
    return min(cap, pol, key=lambda m: ORDER[m])


def request_approval(module: str, action: str, *, entity_type: str | None, entity_id, payload: dict, product_id=None,
                     agent: str | None = None, expires_hours: int = 72) -> str:
    ctx = get_context()
    rid = fetch_one("""INSERT INTO public.approval_requests (tenant_id, module_code, action_code, entity_type, entity_id, product_id,
                         payload, requested_by, requested_by_agent, expires_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s, now() + make_interval(hours => %s)) RETURNING id""",
                    [ctx.tenant_id, module, action, entity_type, entity_id, product_id, json.dumps(payload, default=str),
                     ctx.user_id if ctx.actor_type in ("user", "pilot") else None, agent, expires_hours])[0]
    record_audit("approval.requested", module, entity_type="approval_requests", entity_id=rid,
                 after={"action": action, "entity_type": entity_type, "entity_id": str(entity_id) if entity_id else None})
    from apps.notifications.service import notify
    notify("approval.requested", {"action": f"{module}.{action}"}, permission="approvals.decide")
    return str(rid)


def gate(module: str, action: str, **kw) -> tuple[str, str | None]:
    """Returns (decision, approval_id): 'execute' | 'pending_approval' | 'analysis_only'; raises if disabled."""
    mode = effective_mode(get_context().tenant_id, module, action)
    if mode == "disabled":
        raise BusinessError(f"Action {module}.{action} is disabled for this workspace", "action_disabled", status_code=403)
    if mode == "analysis":
        return "analysis_only", None
    if mode == "approval" and not kw.pop("already_approved", False):
        return "pending_approval", request_approval(module, action, **kw)
    return "execute", None


HANDLERS: dict[str, callable] = {}  # "module.action" -> fn(approval_row) registered by modules


def register(module: str, action: str):
    def deco(fn):
        HANDLERS[f"{module}.{action}"] = fn
        return fn
    return deco


def decide(approval_id: str, approve: bool, reason: str) -> dict:
    ctx = get_context()
    with transaction.atomic():
        row = fetch_one("""SELECT module_code, action_code, entity_type, entity_id, payload, status, expires_at
                             FROM public.approval_requests WHERE id = %s AND tenant_id = %s FOR UPDATE""", [approval_id, ctx.tenant_id])
        if not row:
            raise BusinessError("Approval not found", "not_found", status_code=404)
        module, action, et, eid, payload, status, expires = row
        if status != "pending":
            raise BusinessError(f"Approval already {status}", "invalid_state", status_code=409)
        if expires and expires < timezone.now():
            fetch_one("UPDATE public.approval_requests SET status = 'expired' WHERE id = %s RETURNING 1", [approval_id])
            raise BusinessError("Approval expired", "expired", status_code=410)
        new = "approved" if approve else "rejected"
        fetch_one("""UPDATE public.approval_requests SET status = %s, decided_by = %s, decided_at = now(), decision_reason = %s
                      WHERE id = %s RETURNING 1""", [new, ctx.user_id, reason, approval_id])
        record_audit(f"approval.{new}", module, entity_type="approval_requests", entity_id=approval_id, description=reason,
                     after={"action": action, "entity_type": et, "entity_id": str(eid) if eid else None})
        record_activity(f"approval.{new}", module, entity_type=et, entity_id=eid, description=f"{module}.{action}: {reason}")
    result = {"status": new}
    if approve and (fn := HANDLERS.get(f"{module}.{action}")):
        try:
            out = fn({"id": approval_id, "entity_type": et, "entity_id": str(eid) if eid else None, "payload": payload})
            fetch_one("UPDATE public.approval_requests SET status = 'executed' WHERE id = %s RETURNING 1", [approval_id])
            result |= {"status": "executed", "result": out}
        except BusinessError as e:
            fetch_one("UPDATE public.approval_requests SET status = 'failed', decision_reason = %s WHERE id = %s RETURNING 1",
                      [f"{reason} | execution failed: {e.message}", approval_id])
            result |= {"status": "failed", "error": e.message}
    return result
