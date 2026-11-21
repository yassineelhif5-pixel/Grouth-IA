"""Provider adapters: real connection tests and OAuth flows. A test is 'tested' only if the provider answered."""
from __future__ import annotations

import imaplib
import smtplib
import ssl
from base64 import b64encode
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.utils import timezone

from apps.audit.services import record_audit
from apps.core.db import fetch_one
from apps.core.secrets import decrypt_json

from .gateway import IntegrationError, NotConfigured, get_credentials, http, load_account, set_status, store_credentials

OAUTH = {
    "google": {"auth": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token"},
    "microsoft": {"auth": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                  "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token"},
    "linkedin": {"auth": "https://www.linkedin.com/oauth/v2/authorization", "token": "https://www.linkedin.com/oauth/v2/accessToken"},
    "facebook": {"auth": "https://www.facebook.com/v21.0/dialog/oauth", "token": "https://graph.facebook.com/v21.0/oauth/access_token"},
    "hubspot": {"auth": "https://app.hubspot.com/oauth/authorize", "token": "https://api.hubapi.com/oauth/v1/token"},
    "reddit": {"auth": "https://www.reddit.com/api/v1/authorize", "token": "https://www.reddit.com/api/v1/access_token"},
    "github": {"auth": "https://github.com/login/oauth/authorize", "token": "https://github.com/login/oauth/access_token"},
}
PROVIDER_OAUTH = {
    "gmail": ("google", "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/gmail.send"),
    "google_workspace": ("google", "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/gmail.send"),
    "google_analytics": ("google", "https://www.googleapis.com/auth/analytics.readonly"),
    "google_search_console": ("google", "https://www.googleapis.com/auth/webmasters.readonly"),
    "microsoft_graph": ("microsoft", "offline_access Mail.ReadWrite Mail.Send User.Read"),
    "outlook": ("microsoft", "offline_access Mail.ReadWrite Mail.Send User.Read"),
    "linkedin": ("linkedin", "openid profile w_member_social"),
    "facebook": ("facebook", "pages_manage_posts,pages_read_engagement"),
    "hubspot": ("hubspot", "crm.objects.contacts.read crm.objects.contacts.write"),
    "reddit": ("reddit", "read identity"),
    "github": ("github", "repo"),  # forced correction: write access to the site repository chosen by the tenant
}


def family_of(provider: str) -> str:
    return PROVIDER_OAUTH[provider][0] if provider in PROVIDER_OAUTH else provider


def family_codes(family: str) -> list[str]:
    """Every provider code sharing one OAuth app (so the PILOTE registers Google once for Gmail, Analytics, Search Console…)."""
    return [c for c, (f, _s) in PROVIDER_OAUTH.items() if f == family] or [family]


def family_representative(family: str) -> str:
    return family_codes(family)[0]


def _global_client(provider: str) -> tuple[str, str]:
    codes = family_codes(family_of(provider))
    row = fetch_one("""SELECT g.client_id, g.client_secret_ciphertext FROM public.connector_global_configurations g
                         JOIN public.connector_providers p ON p.id = g.provider_id
                        WHERE p.code = ANY(%s) AND g.is_enabled AND g.client_id IS NOT NULL AND g.deleted_at IS NULL
                        ORDER BY (p.code = %s) DESC LIMIT 1""", [codes, provider])
    if not row or not row[0] or not row[1]:
        raise NotConfigured(f"OAuth client for {provider} is not configured by the PILOTE")
    return row[0], decrypt_json(row[1]).get("client_secret", "")


def redirect_uri() -> str:
    return f"{settings.PUBLIC_API_URL}/api/v1/connectors/oauth/callback"


def oauth_start(account_id: str, return_to: str | None = None) -> str:
    acc = load_account(account_id)
    if acc.provider not in PROVIDER_OAUTH:
        raise NotConfigured("This connector does not use OAuth")
    family, scope = PROVIDER_OAUTH[acc.provider]
    client_id, _ = _global_client(acc.provider)
    back = return_to if return_to and return_to.startswith(f"/t/{acc.tenant_id}/") else None  # only inside this tenant
    state = signing.dumps({"a": acc.id, "t": acc.tenant_id, "r": back}, salt="growth.oauth")
    params = {"client_id": client_id, "redirect_uri": redirect_uri(), "response_type": "code", "scope": scope, "state": state}
    if family == "google":
        params |= {"access_type": "offline", "prompt": "consent"}
    if family == "reddit":
        params |= {"duration": "permanent"}
    return f"{OAUTH[family]['auth']}?{urlencode(params)}"


def oauth_callback(code: str, state: str) -> tuple[str, str | None]:
    data = signing.loads(state, salt="growth.oauth", max_age=900)  # signed + expiring state (CSRF / replay)
    acc = load_account(data["a"])
    family, _ = PROVIDER_OAUTH[acc.provider]
    client_id, secret = _global_client(acc.provider)
    body = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(), "client_id": client_id, "client_secret": secret}
    resp = http("POST", OAUTH[family]["token"], provider=acc.provider, operation="oauth_token", account_id=acc.id, data=body,
                headers={"Accept": "application/json"})
    tok = resp.json()
    if not tok.get("access_token"):
        raise IntegrationError(f"{acc.provider} oauth_token failed: {tok.get('error', 'no access token')}")
    # GitHub OAuth-app tokens do not expire (no expires_in): store them without expiry
    expires = timezone.now() + timezone.timedelta(seconds=int(tok["expires_in"])) if tok.get("expires_in") else None
    store_credentials(acc.id, acc.tenant_id, "oauth_token", {**tok, "expires_at": expires.isoformat() if expires else None},
                      hint="oauth", expires_at=expires)
    set_status(acc.id, "authorized")
    record_audit("connector.authorized", "integrations", entity_type="tenant_connector_accounts", entity_id=acc.id,
                 after={"provider": acc.provider}, tenant_id=acc.tenant_id)
    return acc.tenant_id, data.get("r")


def access_token(account_id: str) -> str:
    """Valid OAuth access token, refreshed when expired (refresh persisted encrypted)."""
    acc = load_account(account_id)
    cred = get_credentials(account_id)
    if cred.get("token"):  # personal access token pasted by the tenant
        return cred["token"]
    exp = cred.get("expires_at")
    if not exp and cred.get("access_token"):  # non-expiring OAuth token (GitHub)
        return cred["access_token"]
    if exp and timezone.datetime.fromisoformat(exp) > timezone.now() + timezone.timedelta(seconds=60):
        return cred["access_token"]
    if not cred.get("refresh_token"):
        set_status(account_id, "expired", "token expired and no refresh token")
        raise NotConfigured("OAuth token expired: reconnect the account")
    family, _ = PROVIDER_OAUTH[acc.provider]
    client_id, secret = _global_client(acc.provider)
    resp = http("POST", OAUTH[family]["token"], provider=acc.provider, operation="oauth_refresh", account_id=account_id,
                data={"grant_type": "refresh_token", "refresh_token": cred["refresh_token"], "client_id": client_id,
                      "client_secret": secret})
    tok = resp.json()
    tok.setdefault("refresh_token", cred["refresh_token"])
    expires = timezone.now() + timezone.timedelta(seconds=int(tok.get("expires_in", 3600)))
    store_credentials(account_id, acc.tenant_id, "oauth_token", {**tok, "expires_at": expires.isoformat()}, "oauth", expires)
    return tok["access_token"]


def _bearer(account_id: str) -> dict:
    return {"Authorization": f"Bearer {access_token(account_id)}"}


def _key(account_id: str) -> dict:
    return get_credentials(account_id)


# ───────────── Real connection tests ─────────────
def _t_smtp(a):
    c = _key(a.id)
    host, port = a.settings.get("host"), int(a.settings.get("port", 587))
    if not host:
        raise NotConfigured("SMTP host missing")
    with smtplib.SMTP(host, port, timeout=15) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(c["username"], c["password"])
        s.noop()


def _t_imap(a):
    c = _key(a.id)
    with imaplib.IMAP4_SSL(a.settings.get("host"), int(a.settings.get("port", 993)), ssl_context=ssl.create_default_context()) as m:
        m.login(c["username"], c["password"])
        m.select("INBOX", readonly=True)


def _t_gmail(a):
    http("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile", provider=a.provider, operation="test", account_id=a.id, headers=_bearer(a.id))


def _t_graph(a):
    http("GET", "https://graph.microsoft.com/v1.0/me", provider=a.provider, operation="test", account_id=a.id, headers=_bearer(a.id))


def _t_sendgrid(a):
    http("GET", "https://api.sendgrid.com/v3/scopes", provider=a.provider, operation="test", account_id=a.id,
         headers={"Authorization": f"Bearer {_key(a.id)['api_key']}"})


def _t_postmark(a):
    http("GET", "https://api.postmarkapp.com/server", provider=a.provider, operation="test", account_id=a.id,
         headers={"X-Postmark-Server-Token": _key(a.id)["api_key"], "Accept": "application/json"})


def _t_mailgun(a):
    domain = a.settings.get("domain")
    base = a.settings.get("base_url", "https://api.mailgun.net")
    http("GET", f"{base}/v3/domains/{domain}", provider=a.provider, operation="test", account_id=a.id, auth=("api", _key(a.id)["api_key"]))


def _t_resend(a):
    http("GET", "https://api.resend.com/domains", provider=a.provider, operation="test", account_id=a.id,
         headers={"Authorization": f"Bearer {_key(a.id)['api_key']}"})


def _t_brevo(a):
    http("GET", "https://api.brevo.com/v3/account", provider=a.provider, operation="test", account_id=a.id, headers={"api-key": _key(a.id)["api_key"]})


def _wp_auth(a) -> dict:
    c = _key(a.id)
    return {"Authorization": "Basic " + b64encode(f"{c['username']}:{c['application_password']}".encode()).decode()}


def _t_wordpress(a):
    http("GET", f"{a.settings['site_url'].rstrip('/')}/wp-json/wp/v2/users/me?context=edit", provider=a.provider, operation="test",
         account_id=a.id, headers=_wp_auth(a))


def _t_ghost(a):
    import jwt as pyjwt
    key_id, secret = _key(a.id)["admin_api_key"].split(":")
    iat = int(timezone.now().timestamp())
    token = pyjwt.encode({"iat": iat, "exp": iat + 300, "aud": "/admin/"}, bytes.fromhex(secret), algorithm="HS256", headers={"kid": key_id})
    http("GET", f"{a.settings['site_url'].rstrip('/')}/ghost/api/admin/site/", provider=a.provider, operation="test", account_id=a.id,
         headers={"Authorization": f"Ghost {token}"})


def _t_rest_cms(a):
    http("GET", a.settings["test_url"], provider=a.provider, operation="test", account_id=a.id,
         headers={"Authorization": f"Bearer {_key(a.id)['api_key']}"})


def _t_whatsapp(a):
    http("GET", f"https://graph.facebook.com/v21.0/{a.settings['phone_number_id']}", provider=a.provider, operation="test",
         account_id=a.id, headers={"Authorization": f"Bearer {_key(a.id)['access_token']}"})


def _t_linkedin(a):
    http("GET", "https://api.linkedin.com/v2/userinfo", provider=a.provider, operation="test", account_id=a.id, headers=_bearer(a.id))


def _t_facebook(a):
    http("GET", "https://graph.facebook.com/v21.0/me", provider=a.provider, operation="test", account_id=a.id, headers=_bearer(a.id))


def _t_stripe(a):
    http("GET", "https://api.stripe.com/v1/balance", provider=a.provider, operation="test", account_id=a.id,
         headers={"Authorization": f"Bearer {_key(a.id)['api_key']}"})


GITHUB_API = "https://api.github.com"


def _t_github(a):
    h = {"Authorization": f"Bearer {access_token(a.id)}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    http("GET", f"{GITHUB_API}/user", provider=a.provider, operation="test", account_id=a.id, headers=h)
    repo = a.settings.get("repo")
    if repo:
        r = http("GET", f"{GITHUB_API}/repos/{repo}", provider=a.provider, operation="test_repo", account_id=a.id, headers=h).json()
        if not (r.get("permissions") or {}).get("push"):
            raise IntegrationError(f"Pas d'accès en écriture au dépôt {repo}")


def _t_pagespeed(a):
    key = (get_credentials(a.id) or {}).get("api_key", "")
    http("GET", "https://www.googleapis.com/pagespeedonline/v5/runPagespeed", provider=a.provider, operation="test",
         account_id=a.id, params={"url": a.settings.get("test_url", "https://example.com"), "key": key})


TESTS = {"smtp": _t_smtp, "imap": _t_imap, "gmail": _t_gmail, "google_workspace": _t_gmail, "microsoft_graph": _t_graph,
         "outlook": _t_graph, "sendgrid": _t_sendgrid, "postmark": _t_postmark, "mailgun": _t_mailgun, "resend": _t_resend,
         "brevo": _t_brevo, "wordpress": _t_wordpress, "ghost": _t_ghost, "rest_cms": _t_rest_cms, "whatsapp_cloud": _t_whatsapp,
         "linkedin": _t_linkedin, "facebook": _t_facebook, "stripe": _t_stripe, "pagespeed": _t_pagespeed,
         "github": _t_github}


def test_connection(account_id: str) -> dict:
    """Real call to the provider. Result persisted (account status, connector_health_checks, audit)."""
    acc = load_account(account_id)
    fn = TESTS.get(acc.provider)
    if not fn:
        set_status(acc.id, "pending_approval", "connector not implemented yet", tested=True)
        return {"status": "pending_approval", "error": "connector not implemented yet"}
    started = timezone.now()
    try:
        fn(acc)
        status, error = "tested", None
    except NotConfigured as e:
        status, error = "not_configured", e.message
    except (IntegrationError, smtplib.SMTPException, imaplib.IMAP4.error, OSError, KeyError, ValueError) as e:
        status, error = "failed", f"{type(e).__name__}: {str(e)[:300]}"
    latency = int((timezone.now() - started).total_seconds() * 1000)
    set_status(acc.id, status, error, tested=True)
    fetch_one("""INSERT INTO public.connector_health_checks (tenant_id, account_id, status, latency_ms, error_message)
                 VALUES (%s, %s, %s, %s, %s) RETURNING id""",
              [acc.tenant_id, acc.id, {"tested": "healthy", "failed": "down"}.get(status, "not_configured"), latency, error])
    record_audit("connector.tested", "integrations", entity_type="tenant_connector_accounts", entity_id=acc.id,
                 status="success" if status == "tested" else "failure", after={"provider": acc.provider, "status": status, "error": error},
                 tenant_id=acc.tenant_id)
    return {"status": status, "error": error, "latency_ms": latency}
