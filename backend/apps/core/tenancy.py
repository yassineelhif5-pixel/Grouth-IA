"""Tenant resolution: the tenant comes from X-Tenant-ID but membership is ALWAYS verified server-side."""
from __future__ import annotations

from dataclasses import dataclass

from rest_framework.exceptions import NotFound, PermissionDenied

from .context import parse_uuid
from .db import fetch_all_dict, fetch_one


@dataclass(frozen=True)
class TenantAccess:
    tenant_id: str
    member_id: str
    roles: tuple[str, ...]
    tenant_status: str


def is_platform_admin(user_id: str) -> bool:
    row = fetch_one(
        "SELECT EXISTS (SELECT 1 FROM public.user_profiles WHERE id = %s AND platform_role_code = 'PILOTE' "
        "AND status = 'active' AND deleted_at IS NULL)", [user_id])
    return bool(row and row[0])


def resolve_tenant(user_id: str, raw_tenant_id: str | None) -> TenantAccess:
    tenant_id = parse_uuid(raw_tenant_id)
    if not tenant_id:
        raise PermissionDenied("X-Tenant-ID header required")
    rows = fetch_all_dict(
        """SELECT m.id AS member_id, t.status AS tenant_status,
                  coalesce(array_agg(r.code) FILTER (WHERE r.code IS NOT NULL), '{}') AS roles
             FROM public.tenant_members m
             JOIN public.tenants t ON t.id = m.tenant_id AND t.deleted_at IS NULL
             LEFT JOIN public.tenant_memberships ms ON ms.member_id = m.id AND ms.tenant_id = m.tenant_id
                  AND ms.deleted_at IS NULL AND (ms.valid_until IS NULL OR ms.valid_until > now())
             LEFT JOIN public.tenant_roles r ON r.id = ms.role_id
            WHERE m.tenant_id = %s AND m.user_id = %s AND m.status = 'active' AND m.deleted_at IS NULL
            GROUP BY m.id, t.status""", [tenant_id, user_id])
    if not rows:
        raise NotFound("Tenant not found")  # do not reveal existence of other tenants
    r = rows[0]
    if r["tenant_status"] in ("suspended", "archived"):
        raise PermissionDenied(f"Tenant is {r['tenant_status']}")
    return TenantAccess(tenant_id, str(r["member_id"]), tuple(r["roles"]), r["tenant_status"])


def has_permission(tenant_id: str, user_id: str, code: str) -> bool:
    row = fetch_one("SELECT app.has_permission(%s::uuid, %s::uuid, %s)", [tenant_id, user_id, code])
    return bool(row and row[0])


def module_enabled(tenant_id: str, module_code: str) -> bool:
    row = fetch_one(
        """SELECT EXISTS (SELECT 1 FROM public.tenant_module_authorizations a
                            JOIN public.platform_modules m ON m.id = a.module_id
                           WHERE a.tenant_id = %s AND m.code = %s AND a.status = 'enabled' AND a.deleted_at IS NULL
                             AND (a.expires_at IS NULL OR a.expires_at > now()) AND m.is_enabled)""",
        [tenant_id, module_code])
    return bool(row and row[0])


def member_license_allows(tenant_id: str, user_id: str, module_code: str) -> bool:
    """User licence check (app.member_license_allows): owners/admins and tenants without licence allocations are never restricted."""
    row = fetch_one("SELECT app.member_license_allows(%s::uuid, %s::uuid, %s)", [tenant_id, user_id, module_code])
    return bool(row and row[0])
