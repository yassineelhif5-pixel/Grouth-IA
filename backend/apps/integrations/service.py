"""GrowthAiConnectorService — the single façade every module uses to act through a tenant's connectors.

Instead of each feature talking to GitHub / a CMS / a social network directly, it asks this service to perform
the capability (push the SEO/GEO files to the site source, publish an article, post to a channel, send an email…).
The service resolves the right connector for the tenant, checks it is connected, performs the real API call and
records it. Nothing is simulated; if no connector can fulfil the capability it raises a clear, actionable error.

Today it implements the site-source capability (push files, replacing the existing ones) over GitHub. Other
capabilities delegate to the existing per-channel services and are added here as connectors gain write support.
"""
from __future__ import annotations

from apps.core.exceptions import BusinessError


class GrowthAiConnectorService:
    # ───────────────────────── site source (SEO/GEO files) ─────────────────────────
    @staticmethod
    def site_source(tenant_id: str) -> dict | None:
        """The connected site-source account (GitHub) for this tenant, or None if not configured."""
        from apps.visibility import site_access
        account_id = site_access.resolve_account(tenant_id)
        return None if not account_id else {"provider": "github", "account_id": account_id}

    @staticmethod
    def push_site_files(tenant_id: str, files: list[dict], mode: str | None = None) -> dict:
        """Push files to the tenant's site source in one commit, replacing the existing ones (PR or direct)."""
        from apps.visibility import site_access
        account_id = site_access.resolve_account(tenant_id)
        if not account_id:
            raise BusinessError("Aucun accès au site n'est configuré (connectez le dépôt GitHub du site)", "site_source_not_configured")
        return site_access.commit_files(account_id, files, mode)

    @staticmethod
    def push_recommendation_files(tenant_id: str, rec_ids: list[str], mode: str | None = None) -> dict:
        """Build the files of the given SEO/GEO recommendations and push them, then mark the recommendations applied.
        This is what a validated 'forced correction' action or scheduler run calls."""
        from apps.visibility import site_access
        account_id = site_access.resolve_account(tenant_id)
        if not account_id:
            raise BusinessError("Aucun accès au site n'est configuré (connectez le dépôt GitHub du site)", "site_source_not_configured")
        files, applied = site_access.files_for_recommendations(rec_ids, account_id)
        if not files:
            raise BusinessError("Aucune des actions sélectionnées ne produit de fichier à pousser", "nothing_to_apply")
        result = site_access.commit_files(account_id, files, mode)
        site_access.mark_applied(applied, result)
        return result | {"applied": applied}


# Module-level singleton used as "the service" across the codebase.
service = GrowthAiConnectorService()
