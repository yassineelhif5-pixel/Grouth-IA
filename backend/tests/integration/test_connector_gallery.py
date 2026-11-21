"""Simplified connector gallery: one-click OAuth where the PILOTE registered the app, guided forms otherwise."""
import pytest

from .test_prompt3_licenses_visibility import _enterprise

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "logs"])


def test_catalog_connect_and_family_oauth(tenant_user, make_user, admin_conn):
    owner, pilot = tenant_user(), make_user(pilot=True)
    _enterprise(pilot, owner["tenant_id"])
    c = owner["client"]

    cat = c.get("/api/v1/connectors/catalog")
    assert cat.status_code == 200, cat.content
    by = {p["code"]: p for p in cat.json()["providers"]}
    assert by["stripe"]["method"] == "api_key" and any(f["name"] == "api_key" and f["secret"] for f in by["stripe"]["fields"])
    assert by["wordpress"]["settings_fields"] and by["wordpress"]["method"] == "api_key"
    assert by["gmail"]["method"] == "oauth" and by["gmail"]["oauth_available"] is False and by["gmail"]["family_label"] == "Google"
    assert by["github"]["method"] == "oauth_or_key"
    assert cat.json()["redirect_uri"].endswith("/api/v1/connectors/oauth/callback")

    # api_key provider: one connect call creates the account, the guided form saves fields, stored encrypted
    conn = c.post("/api/v1/connectors/connect", {"provider_code": "stripe"}, format="json").json()
    assert conn["method"] == "api_key" and conn["account_id"]
    c.post(f"/api/v1/connector-accounts/{conn['account_id']}/credentials",
           {"credential_type": "api_key", "secrets": {"api_key": "sk_test_" + "x" * 24}}, format="json")
    cipher = admin_conn.execute("SELECT ciphertext FROM public.tenant_connector_credentials WHERE account_id = %s AND deleted_at IS NULL",
                                [conn["account_id"]]).fetchone()[0]
    assert "sk_test_" not in cipher

    # pure OAuth provider, not yet registered by the PILOTE → clear, actionable error (no silent failure)
    r = c.post("/api/v1/connectors/connect", {"provider_code": "gmail"}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "oauth_not_configured"

    # PILOTE registers the Google OAuth app once → every Google service becomes one-click
    fams = {f["family"]: f for f in pilot["client"].get("/api/v1/pilot/oauth-clients").json()}
    assert fams["google"]["configured"] is False and fams["google"]["redirect_uri"].endswith("/connectors/oauth/callback")
    assert "gmail" in fams["google"]["providers"] and fams["google"]["steps"]
    reg = pilot["client"].post("/api/v1/pilot/oauth-clients",
                               {"family": "google", "client_id": "gid.apps.googleusercontent.com", "client_secret": "gsecret"}, format="json")
    assert reg.status_code == 200, reg.content
    secret_cipher = admin_conn.execute("""SELECT g.client_secret_ciphertext FROM public.connector_global_configurations g
                                           JOIN public.connector_providers p ON p.id = g.provider_id
                                           WHERE p.code = ANY(%s)""", [["gmail", "google_analytics", "google_search_console", "google_workspace"]]).fetchone()[0]
    assert "gsecret" not in secret_cipher  # PILOTE secret stored encrypted
    cat2 = {p["code"]: p for p in c.get("/api/v1/connectors/catalog").json()["providers"]}
    assert cat2["gmail"]["oauth_available"] and cat2["google_search_console"]["oauth_available"]  # family reuse, configured once

    conn2 = c.post("/api/v1/connectors/connect",
                   {"provider_code": "gmail", "return_to": f"/t/{owner['tenant_id']}/connectors"}, format="json").json()
    url = conn2["authorization_url"]
    assert "accounts.google.com" in url and "gmail.modify" in url and "redirect_uri=" in url and "state=" in url

    # GitHub supports both: forcing the key method returns the guided-form path even though OAuth exists
    g = c.post("/api/v1/connectors/connect", {"provider_code": "github", "method": "api_key"}, format="json").json()
    assert g["method"] == "api_key" and g["account_id"]

    # a provider the PILOTE disabled for this tenant cannot be connected
    admin_conn.execute("""UPDATE public.tenant_connector_authorizations SET status = 'disabled'
                          WHERE tenant_id = %s AND provider_id = (SELECT id FROM public.connector_providers WHERE code = 'stripe')""",
                       [owner["tenant_id"]])
    assert c.post("/api/v1/connectors/connect", {"provider_code": "stripe"}, format="json").status_code == 403
