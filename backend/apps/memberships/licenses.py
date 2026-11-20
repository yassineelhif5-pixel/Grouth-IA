"""User licences: the PILOTE declares how many licences of each type a tenant may use, tenant admins assign them.

Rules
- one active licence per member; assignment never exceeds the tenant's allocation (row lock on the allocation)
- the allocation can never be lowered below the number of licences already assigned
- a tenant without any allocation has no licence restriction (backward compatible); the first time licences are
  managed, a default allocation is created (FULL = members quota) and existing members receive a FULL licence
- every change is versioned (entity_history) and audited
"""
from __future__ import annotations

import requests
from django.conf import settings
from django.db import transaction

from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError

ALLOCATIONS_SQL = """
SELECT lt.code, lt.name, lt.description, lt.modules, lt.sort_order,
       coalesce(a.quantity, 0) AS quantity, a.id AS allocation_id,
       (SELECT count(*) FROM public.member_license_assignments la
          JOIN public.tenant_members m ON m.id = la.member_id AND m.deleted_at IS NULL AND m.status <> 'removed'
         WHERE la.tenant_id = %s AND la.license_type_id = lt.id AND la.status = 'active' AND la.deleted_at IS NULL) AS used
  FROM public.license_types lt
  LEFT JOIN public.tenant_license_allocations a ON a.license_type_id = lt.id AND a.tenant_id = %s AND a.deleted_at IS NULL
 WHERE lt.is_active
 ORDER BY lt.sort_order"""


def _has_allocations(tenant_id: str) -> bool:
    return bool(fetch_one("SELECT EXISTS (SELECT 1 FROM public.tenant_license_allocations WHERE tenant_id = %s AND deleted_at IS NULL)",
                          [tenant_id])[0])


def ensure_default_allocations(tenant_id: str) -> None:
    """First use: FULL licences = members quota, existing members receive one (nobody loses access)."""
    if _has_allocations(tenant_id):
        return
    from apps.licensing.services import effective_limit
    members = fetch_all_dict("""SELECT m.id FROM public.tenant_members m
                                 WHERE m.tenant_id = %s AND m.deleted_at IS NULL AND m.status <> 'removed' ORDER BY m.joined_at""",
                             [tenant_id])
    limit = effective_limit(tenant_id, "members.max")
    quantity = max(limit if limit is not None else len(members), len(members))
    with transaction.atomic():
        fetch_one("""INSERT INTO public.tenant_license_allocations (tenant_id, license_type_id, quantity, note)
                     SELECT %s, id, %s, 'allocation initiale (quota membres)' FROM public.license_types WHERE code = 'FULL'
                     ON CONFLICT DO NOTHING RETURNING id""", [tenant_id, quantity])
        for m in members:
            fetch_one("""INSERT INTO public.member_license_assignments (tenant_id, member_id, license_type_id, assigned_by, reason)
                         SELECT %s, %s, id, %s, 'attribution initiale' FROM public.license_types WHERE code = 'FULL'
                         ON CONFLICT DO NOTHING RETURNING id""", [tenant_id, m["id"], get_context().user_id])
        record_audit("licenses.initialized", "licensing", entity_type="tenant_license_allocations",
                     after={"FULL": quantity, "members": len(members)})


def allocations(tenant_id: str) -> list[dict]:
    ensure_default_allocations(tenant_id)
    rows = fetch_all_dict(ALLOCATIONS_SQL, [tenant_id, tenant_id])
    for r in rows:
        r["available"] = max(int(r["quantity"]) - int(r["used"]), 0)
    return rows


def set_allocations(tenant_id: str, quantities: dict[str, int], reason: str) -> list[dict]:
    """PILOTE: declare the number of licences of each type for a tenant."""
    ensure_default_allocations(tenant_id)
    current = {r["code"]: r for r in fetch_all_dict(ALLOCATIONS_SQL, [tenant_id, tenant_id])}
    with transaction.atomic():
        for code, qty in quantities.items():
            if code not in current:
                raise BusinessError(f"Type de licence inconnu : {code}", "invalid_license_type")
            qty = int(qty)
            if qty < 0:
                raise BusinessError("La quantité doit être positive", "invalid_quantity")
            used = int(current[code]["used"])
            if qty < used:
                raise BusinessError(f"{used} licence(s) {current[code]['name']} sont déjà attribuées : retirez-les avant de "
                                    f"descendre à {qty}.", "allocation_below_usage", status_code=409)
            fetch_one("""INSERT INTO public.tenant_license_allocations (tenant_id, license_type_id, quantity, note)
                         SELECT %s, id, %s, %s FROM public.license_types WHERE code = %s
                         ON CONFLICT (tenant_id, license_type_id) WHERE deleted_at IS NULL
                         DO UPDATE SET quantity = EXCLUDED.quantity, note = EXCLUDED.note RETURNING id""",
                      [tenant_id, qty, reason, code])
        record_audit("licenses.allocations_updated", "licensing", entity_type="tenant_license_allocations",
                     before={c: int(r["quantity"]) for c, r in current.items()}, after=quantities, description=reason)
        record_activity("licenses.allocations_updated", "licensing", entity_type="tenant_license_allocations",
                        description="Licences disponibles mises à jour par le PILOTE")
    return allocations(tenant_id)


def assign_license(tenant_id: str, member_id: str, license_code: str | None, reason: str = "") -> None:
    """Admin: give (or change, or remove with None) the licence of a member, within the available allocation."""
    ensure_default_allocations(tenant_id)
    with transaction.atomic():
        member = fetch_one("""SELECT id FROM public.tenant_members WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL
                              AND status <> 'removed'""", [member_id, tenant_id])
        if not member:
            raise BusinessError("Membre introuvable", "not_found", status_code=404)
        current = fetch_one("""SELECT la.id, lt.code FROM public.member_license_assignments la
                                 JOIN public.license_types lt ON lt.id = la.license_type_id
                                WHERE la.tenant_id = %s AND la.member_id = %s AND la.deleted_at IS NULL FOR UPDATE OF la""",
                            [tenant_id, member_id])
        if license_code is None:
            if current:
                fetch_one("""UPDATE public.member_license_assignments SET status = 'revoked', revoked_at = now(), reason = %s
                             WHERE id = %s RETURNING 1""", [reason or "licence retirée", current[0]])
            record_audit("license.revoked", "licensing", entity_type="tenant_members", entity_id=member_id,
                         before={"license": current[1] if current else None}, after={"license": None}, description=reason)
            return
        alloc = fetch_one("""SELECT a.id, a.quantity, lt.id, lt.name FROM public.tenant_license_allocations a
                               JOIN public.license_types lt ON lt.id = a.license_type_id
                              WHERE a.tenant_id = %s AND lt.code = %s AND a.deleted_at IS NULL AND lt.is_active
                              FOR UPDATE OF a""", [tenant_id, license_code])
        if not alloc:
            raise BusinessError("Aucune licence de ce type n'est disponible pour ce tenant.", "license_unavailable", status_code=409)
        used = fetch_one("""SELECT count(*) FROM public.member_license_assignments la
                              JOIN public.tenant_members m ON m.id = la.member_id AND m.deleted_at IS NULL AND m.status <> 'removed'
                             WHERE la.tenant_id = %s AND la.license_type_id = %s AND la.status = 'active' AND la.deleted_at IS NULL
                               AND la.member_id <> %s""", [tenant_id, alloc[2], member_id])[0]
        if used >= alloc[1]:
            raise BusinessError(f"Toutes les licences « {alloc[3]} » sont attribuées ({alloc[1]}/{alloc[1]}). Demandez au PILOTE "
                                "d'en ajouter ou retirez-en une à un autre utilisateur.", "license_exhausted", status_code=409)
        if current:
            fetch_one("""UPDATE public.member_license_assignments SET license_type_id = %s, status = 'active', revoked_at = NULL,
                                assigned_by = %s, assigned_at = now(), reason = %s WHERE id = %s RETURNING 1""",
                      [alloc[2], get_context().user_id, reason or "changement de licence", current[0]])
        else:
            fetch_one("""INSERT INTO public.member_license_assignments (tenant_id, member_id, license_type_id, assigned_by, reason)
                         VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                      [tenant_id, member_id, alloc[2], get_context().user_id, reason or "attribution"])
        record_audit("license.assigned", "licensing", entity_type="tenant_members", entity_id=member_id,
                     before={"license": current[1] if current else None}, after={"license": license_code}, description=reason)
        record_activity("license.assigned", "licensing", entity_type="tenant_members", entity_id=member_id,
                        description=f"Licence {alloc[3]} attribuée")


def license_allows(tenant_id: str, user_id: str, module_code: str) -> bool:
    row = fetch_one("SELECT app.member_license_allows(%s::uuid, %s::uuid, %s)", [tenant_id, user_id, module_code])
    return bool(row and row[0])


def send_supabase_invite(email: str, redirect_path: str) -> str:
    """Optional: ask Supabase Auth to e-mail the invitation (needs SUPABASE_SERVICE_ROLE_KEY, backend only).

    Returns 'sent', 'not_configured' or 'failed:<reason>' — never pretends it was sent."""
    key = getattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "")
    if not key or not settings.SUPABASE_URL:
        return "not_configured"
    try:
        r = requests.post(f"{settings.SUPABASE_URL}/auth/v1/invite", json={"email": email},
                          params={"redirect_to": f"{settings.GROWTH['FRONTEND_URL']}{redirect_path}"},
                          headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=15)
    except requests.RequestException as e:
        return f"failed:{type(e).__name__}"
    if r.status_code in (200, 201):
        return "sent"
    if r.status_code == 422:  # already registered: the in-app invitation link is enough
        return "already_registered"
    return f"failed:{r.status_code}"
