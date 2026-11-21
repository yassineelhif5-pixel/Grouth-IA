"""Self-service connection: the tenant connects a provider itself. The PILOTE keeps the last word (it can
disable or suspend a provider for a tenant), but a provider never touched by the PILOTE is open by default,
so the user can authorize Growth IA on their own account without waiting for an approval step.
"""
from __future__ import annotations

from apps.core.db import fetch_one
from apps.core.exceptions import BusinessError


def _ensure_authorized(request, code: str) -> None:
    row = fetch_one("""SELECT a.status FROM public.tenant_connector_authorizations a JOIN public.connector_providers p ON p.id = a.provider_id
                        WHERE a.tenant_id = %s AND p.code = %s AND a.deleted_at IS NULL""", [request.tenant.tenant_id, code])
    if row and row[0] != "enabled":
        raise BusinessError("Ce connecteur a été désactivé par le PILOTE pour votre espace", "connector_suspended", status_code=403)
    if not row:
        fetch_one("""INSERT INTO public.tenant_connector_authorizations (tenant_id, provider_id, status, granted_by, reason)
                     SELECT %s, id, 'enabled', %s, 'Connexion en libre-service par le tenant' FROM public.connector_providers WHERE code = %s
                     ON CONFLICT (tenant_id, provider_id) WHERE deleted_at IS NULL DO NOTHING RETURNING id""",
                  [request.tenant.tenant_id, request.user.id, code])


def ensure_account(request, code: str) -> str:
    """Authorize (unless the PILOTE blocked it) and return the single account id for this provider, creating it if needed."""
    if not fetch_one("SELECT 1 FROM public.connector_providers WHERE code = %s AND is_enabled", [code]):
        raise BusinessError("Fournisseur inconnu", "unknown_provider", status_code=404)
    _ensure_authorized(request, code)
    row = fetch_one("""SELECT a.id FROM public.tenant_connector_accounts a JOIN public.connector_providers p ON p.id = a.provider_id
                        WHERE a.tenant_id = %s AND p.code = %s AND a.deleted_at IS NULL ORDER BY a.created_at LIMIT 1""",
                    [request.tenant.tenant_id, code])
    if row:
        return str(row[0])
    created = fetch_one("""INSERT INTO public.tenant_connector_accounts (tenant_id, provider_id, display_name, status, connected_by, settings)
                           SELECT %s, id, name, 'pending', %s, '{}'::jsonb FROM public.connector_providers WHERE code = %s RETURNING id""",
                        [request.tenant.tenant_id, request.user.id, code])
    return str(created[0])
