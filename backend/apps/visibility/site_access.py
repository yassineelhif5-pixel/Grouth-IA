"""Forced correction: Growth IA writes the validated fixes directly into the tenant's site source.

Access is granted by the tenant (GitHub OAuth when the PILOTE configured the OAuth app, otherwise a fine-grained token
limited to the chosen repository). Fixes land in ONE commit, either as a pull request (default, reviewable) or directly
on the chosen branch when the tenant explicitly selects "replace directly". The repository history is the backup.
Only root files (robots.txt, sitemaps, llms.txt, 404.html…) are placed at their real path; <head> snippets cannot be
injected blindly into an unknown template, so they are committed under growth-ia/ with integration notes.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from apps.audit.services import record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.integrations.gateway import IntegrationError, NotConfigured, http, load_account, set_status, store_credentials

ROOT_FILES = {"robots_txt": "robots.txt", "sitemap_xml": "sitemap.xml", "sitemap_images_xml": "sitemap-images.xml",
              "llms_txt": "llms.txt", "page_404": "404.html"}
SNIPPETS = {"json_ld", "open_graph", "hreflang", "canonical", "redirects"}
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PATH_RE = re.compile(r"^[A-Za-z0-9_./-]*$")


def _headers(account_id: str) -> dict:
    from apps.integrations.providers import access_token
    return {"Authorization": f"Bearer {access_token(account_id)}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _gh(method: str, path: str, account_id: str, operation: str, **kw):
    from apps.integrations import providers
    return http(method, f"{providers.GITHUB_API}{path}", provider="github", operation=operation, account_id=account_id,
                headers=_headers(account_id), **kw)


def _ensure_authorized(tid: str) -> None:
    """Site access is enabled per tenant; a PILOTE suspension (disabled/suspended) is respected."""
    row = fetch_one("""SELECT a.status FROM public.tenant_connector_authorizations a JOIN public.connector_providers p ON p.id = a.provider_id
                        WHERE a.tenant_id = %s AND p.code = 'github' AND a.deleted_at IS NULL""", [tid])
    if row and row[0] != "enabled":
        raise BusinessError("L'accès au site via GitHub a été suspendu par le PILOTE pour cet espace", "connector_suspended", status_code=403)
    if not row:
        fetch_one("""INSERT INTO public.tenant_connector_authorizations (tenant_id, provider_id, status, granted_by, reason)
                     SELECT %s, id, 'enabled', %s, 'Correction forcée : accès au site demandé par le tenant'
                       FROM public.connector_providers WHERE code = 'github' RETURNING id""", [tid, get_context().user_id])


def status() -> dict:
    tid = get_context().tenant_id
    accounts = fetch_all_dict("""SELECT a.id, a.display_name, a.status, a.settings, a.last_error, a.last_test_at,
                                        (SELECT masked_hint FROM public.tenant_connector_credentials c WHERE c.account_id = a.id
                                          AND c.deleted_at IS NULL ORDER BY c.created_at DESC LIMIT 1) AS credential_hint
                                   FROM public.tenant_connector_accounts a JOIN public.connector_providers p ON p.id = a.provider_id
                                  WHERE a.tenant_id = %s AND p.code = 'github' AND a.deleted_at IS NULL ORDER BY a.created_at""", [tid])
    oauth = bool(fetch_one("""SELECT EXISTS (SELECT 1 FROM public.connector_global_configurations g JOIN public.connector_providers p
                               ON p.id = g.provider_id WHERE p.code = 'github' AND g.is_enabled AND g.client_id IS NOT NULL)""")[0])
    return {"accounts": accounts, "oauth_available": oauth,
            "token_help": "Jeton GitHub « fine-grained » limité au dépôt du site, permissions Contents et Pull requests en lecture/écriture."}


def _account_for(tid: str) -> str:
    row = fetch_one("""SELECT a.id FROM public.tenant_connector_accounts a JOIN public.connector_providers p ON p.id = a.provider_id
                        WHERE a.tenant_id = %s AND p.code = 'github' AND a.deleted_at IS NULL ORDER BY a.created_at LIMIT 1""", [tid])
    if row:
        return str(row[0])
    return str(fetch_one("""INSERT INTO public.tenant_connector_accounts (tenant_id, provider_id, display_name, status, connected_by, settings)
                            SELECT %s, id, 'GitHub — site', 'pending', %s, '{}'::jsonb FROM public.connector_providers WHERE code = 'github'
                            RETURNING id""", [tid, get_context().user_id])[0])


def connect(token: str | None, return_to: str | None) -> dict:
    """Token pasted → stored encrypted and tested now. No token → OAuth URL (GitHub authorization screen)."""
    from apps.integrations.providers import oauth_start, test_connection
    tid = get_context().tenant_id
    _ensure_authorized(tid)
    aid = _account_for(tid)
    if token:
        token = token.strip()
        if not re.match(r"^(github_pat_|ghp_|gho_|ghu_)[A-Za-z0-9_]{20,}$", token):
            raise BusinessError("Ce jeton ne ressemble pas à un jeton GitHub", "invalid_token")
        store_credentials(aid, tid, "api_key", {"token": token}, hint=f"••••{token[-4:]}")
        res = test_connection(aid)
        if res.get("status") != "tested":
            raise BusinessError(f"GitHub a refusé le jeton : {res.get('error')}", "token_rejected")
        record_audit("site_access.connected", "visibility", entity_type="tenant_connector_accounts", entity_id=aid, after={"method": "token"})
        return {"account_id": aid, "status": "tested"}
    try:
        return {"account_id": aid, "authorization_url": oauth_start(aid, return_to)}
    except NotConfigured as e:
        raise BusinessError("La connexion GitHub en un clic n'est pas encore configurée par le PILOTE : utilisez un jeton d'accès.",
                            "oauth_not_configured") from e


def repos(account_id: str) -> list[dict]:
    _own(account_id)
    out = []
    for page in (1, 2, 3):
        rows = _gh("GET", "/user/repos", account_id, "list_repos",
                   params={"per_page": 100, "page": page, "sort": "pushed", "affiliation": "owner,collaborator,organization_member"}).json()
        out += [{"full_name": r["full_name"], "default_branch": r.get("default_branch") or "main", "private": r.get("private"),
                 "pushed_at": r.get("pushed_at"), "can_push": bool((r.get("permissions") or {}).get("push")), "homepage": r.get("homepage")}
                for r in rows]
        if len(rows) < 100:
            break
    return [r for r in out if r["can_push"]]


def configure(account_id: str, repo: str, branch: str | None, base_path: str, mode: str) -> dict:
    from apps.integrations.providers import test_connection
    _own(account_id)
    from apps.integrations.providers import normalize_repo
    repo = normalize_repo(repo)
    if not REPO_RE.match(repo):
        raise BusinessError("Dépôt invalide : indiquez le lien GitHub ou propriétaire/nom", "invalid_repo")
    base_path = (base_path or "").strip().strip("/")
    if not PATH_RE.match(base_path) or ".." in base_path:
        raise BusinessError("Dossier invalide", "invalid_path")
    if mode not in ("pull_request", "direct"):
        raise BusinessError("Mode invalide", "invalid_mode")
    info = _gh("GET", f"/repos/{repo}", account_id, "get_repo").json()
    branch = branch or info.get("default_branch") or "main"
    settings = {"repo": repo, "branch": branch, "base_path": base_path, "mode": mode}
    fetch_one("UPDATE public.tenant_connector_accounts SET settings = %s::jsonb, external_account_id = %s, display_name = %s WHERE id = %s RETURNING 1",
              [json.dumps(settings), repo, f"GitHub — {repo}", account_id])
    res = test_connection(account_id)
    if res.get("status") != "tested":
        raise BusinessError(f"Accès au dépôt impossible : {res.get('error')}", "repo_unreachable")
    record_audit("site_access.configured", "visibility", entity_type="tenant_connector_accounts", entity_id=account_id, after=settings)
    return settings


def _own(account_id: str):
    acc = load_account(account_id)
    if acc.tenant_id != get_context().tenant_id or acc.provider != "github":
        raise BusinessError("Accès au site introuvable", "not_found", status_code=404)
    return acc


def _files_for(rec_ids: list[str], base: str) -> tuple[list[dict], list[str]]:
    tid = get_context().tenant_id
    rows = fetch_all_dict("""SELECT r.id, r.title, r.apply_mode, a.asset_type, a.filename, a.content
                               FROM public.visibility_recommendations r
                               LEFT JOIN public.visibility_generated_assets a ON a.id = nullif(r.evidence->>'asset_id', '')::uuid
                              WHERE r.tenant_id = %s AND r.deleted_at IS NULL AND r.id = ANY(%s::uuid[])""", [tid, rec_ids])
    files, applied = [], []
    for r in rows:
        if r["apply_mode"] != "generated_file" or not r["asset_type"]:
            continue
        if r["asset_type"] in ROOT_FILES:
            path = ROOT_FILES[r["asset_type"]]
            content = r["content"]
        else:  # <head> snippet / server config: committed for integration, never injected blindly
            path = f"growth-ia/{r['filename']}"
            note = ("<!-- Growth IA : à intégrer dans le <head> de vos pages (gabarit commun). -->\n" if r["asset_type"] in SNIPPETS - {"redirects"}
                    else "# Growth IA : règles de redirection 301 à intégrer dans la configuration du serveur.\n")
            content = note + (r["content"] or "")
        files.append({"path": f"{base}/{path}" if base else path, "content": content, "rec_id": str(r["id"]), "title": r["title"]})
        applied.append(str(r["id"]))
    return files, applied


def resolve_account(tenant_id: str) -> str | None:
    """The tenant's single connected GitHub (site source) account, if any — used by the connector service."""
    row = fetch_one("""SELECT a.id FROM public.tenant_connector_accounts a JOIN public.connector_providers p ON p.id = a.provider_id
                        WHERE a.tenant_id = %s AND p.code = 'github' AND a.deleted_at IS NULL
                          AND nullif(a.settings->>'repo','') IS NOT NULL ORDER BY a.created_at LIMIT 1""", [tenant_id])
    return str(row[0]) if row else None


def commit_files(account_id: str, files: list[dict], mode: str | None = None, force: bool = False) -> dict:
    """Low-level push primitive: write every file in ONE commit, replacing the existing ones, as a PR or directly.
    force=True pushes straight onto the default branch (main), overwriting the files there (a force update of the ref).
    `files` = [{"path","content","title"?}]. Paths are taken as given (already under the repo's public folder)."""
    acc = _own(account_id)
    cfg = acc.settings or {}
    if not cfg.get("repo"):
        raise BusinessError("Choisissez d'abord le dépôt du site", "repo_not_configured")
    mode = "direct" if force else (mode or cfg.get("mode") or "pull_request")
    if not files:
        raise BusinessError("Aucun fichier à pousser", "nothing_to_apply")
    repo, base = cfg["repo"], cfg.get("branch") or "main"
    for f in files:
        f.setdefault("title", f["path"])
    try:
        head = _gh("GET", f"/repos/{repo}/git/ref/heads/{base}", account_id, "get_ref").json()["object"]["sha"]
        base_tree = _gh("GET", f"/repos/{repo}/git/commits/{head}", account_id, "get_commit").json()["tree"]["sha"]
        tree = _gh("POST", f"/repos/{repo}/git/trees", account_id, "create_tree",
                   json={"base_tree": base_tree, "tree": [{"path": f["path"], "mode": "100644", "type": "blob", "content": f["content"]} for f in files]}).json()
        msg = "Growth IA : corrections SEO/GEO\n\n" + "\n".join(f"- {f['path']} : {f['title']}" for f in files)
        commit = _gh("POST", f"/repos/{repo}/git/commits", account_id, "create_commit",
                     json={"message": msg, "tree": tree["sha"], "parents": [head]}).json()
        result: dict = {"repo": repo, "mode": mode, "commit_sha": commit["sha"], "files": [f["path"] for f in files]}
        if mode == "direct":
            _gh("PATCH", f"/repos/{repo}/git/refs/heads/{base}", account_id, "update_ref", json={"sha": commit["sha"], "force": force})
            result |= {"branch": base, "force_push": force, "url": f"https://github.com/{repo}/commit/{commit['sha']}"}
        else:
            branch = f"growth-ia/corrections-{datetime.now(UTC):%Y%m%d-%H%M%S}"
            _gh("POST", f"/repos/{repo}/git/refs", account_id, "create_ref", json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
            pr = _gh("POST", f"/repos/{repo}/pulls", account_id, "create_pr",
                     json={"title": "Growth IA : corrections SEO/GEO", "head": branch, "base": base,
                           "body": "Corrections générées par Growth IA à partir de l'audit du site.\n\n" + "\n".join(f"- `{f['path']}` — {f['title']}" for f in files)
                                   + "\n\nLes extraits du dossier `growth-ia/` sont à intégrer dans le gabarit (balises <head>, configuration serveur)."}).json()
            result |= {"branch": branch, "url": pr.get("html_url"), "pull_request": pr.get("number")}
    except IntegrationError as e:
        set_status(account_id, "failed", e.message)
        raise BusinessError(f"GitHub a refusé l'opération : {e.message}", "github_error") from e
    record_audit("site_access.pushed", "visibility", entity_type="tenant_connector_accounts", entity_id=account_id,
                 after={k: v for k, v in result.items() if k != "files"} | {"files": len(files)})
    return result


def files_for_recommendations(rec_ids: list[str], account_id: str) -> tuple[list[dict], list[str]]:
    base = (_own(account_id).settings or {}).get("base_path", "")
    return _files_for(rec_ids, base)


def generated_file_rec_ids(audit_id: str) -> list[str]:
    """Every recommendation of an audit that produces a file to place on the site (for 'fix all')."""
    tid = get_context().tenant_id
    rows = fetch_all_dict("""SELECT r.id FROM public.visibility_recommendations r
                               JOIN public.visibility_generated_assets a ON a.id = nullif(r.evidence->>'asset_id','')::uuid
                              WHERE r.tenant_id = %s AND r.audit_id = %s AND r.deleted_at IS NULL AND r.apply_mode = 'generated_file'
                              ORDER BY r.priority""", [tid, audit_id])
    return [str(r["id"]) for r in rows]


def mark_applied(rec_ids: list[str], result: dict) -> None:
    for rid in rec_ids:
        fetch_one("""UPDATE public.visibility_recommendations SET status = 'applied', applied_at = now(),
                     applied_result = coalesce(applied_result, '{}'::jsonb) || %s::jsonb WHERE id = %s RETURNING 1""",
                  [json.dumps({"forced": result}), rid])


def apply(account_id: str, rec_ids: list[str], mode: str | None = None) -> dict:
    """Immediate forced correction from the UI: build files from the recommendations and push them in one commit."""
    files, applied = files_for_recommendations(rec_ids, account_id)
    if not files:
        raise BusinessError("Aucune des actions sélectionnées ne produit de fichier à placer dans le dépôt", "nothing_to_apply")
    result = commit_files(account_id, files, mode)
    mark_applied(applied, result)
    return result
