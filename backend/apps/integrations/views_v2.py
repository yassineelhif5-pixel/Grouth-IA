from django.conf import settings
from django.http import HttpResponseRedirect
from rest_framework import serializers
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.core.redaction import mask_hint
from apps.core.secrets import encrypt_json
from apps.core.views import GrowthAPIView
from apps.core.webhooks import PublicWebhookView

from .gateway import load_account, set_status, store_credentials
from .providers import oauth_callback, oauth_start, test_connection

SECRET_FIELDS = {"api_key", "password", "application_password", "access_token", "admin_api_key", "app_secret", "webhook_secret",
                 "verify_token", "client_secret", "signing_key", "inbound_token"}


class CredentialSerializer(serializers.Serializer):
    credential_type = serializers.ChoiceField(choices=["api_key", "basic", "webhook_secret", "oauth_token"])
    secrets = serializers.DictField(child=serializers.CharField(max_length=4000))
    settings = serializers.DictField(required=False)


def _account(request, account_id):
    acc = load_account(str(account_id))
    if acc.tenant_id != request.tenant.tenant_id:
        raise BusinessError("Connector account not found", "not_found", status_code=404)
    return acc


class CredentialsView(GrowthAPIView):
    """Store secrets (encrypted backend-side). Values are never returned — only a masked hint."""
    permission_map = {"*": "connectors.manage"}

    def post(self, request, account_id):
        acc = _account(request, account_id)
        ser = CredentialSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        hint_src = next((v for k, v in d["secrets"].items() if k in SECRET_FIELDS), "")
        store_credentials(acc.id, acc.tenant_id, d["credential_type"], d["secrets"], hint=mask_hint(hint_src))
        if d.get("settings"):
            fetch_one("UPDATE public.tenant_connector_accounts SET settings = settings || %s::jsonb WHERE id = %s RETURNING 1",
                      [__import__("json").dumps(d["settings"]), acc.id])
        set_status(acc.id, "configured")
        record_audit("connector.credentials_updated", "integrations", entity_type="tenant_connector_accounts", entity_id=acc.id,
                     after={"provider": acc.provider, "fields": sorted(d["secrets"].keys())})
        return Response({"status": "configured", "hint": mask_hint(hint_src)})


class TestView(GrowthAPIView):
    permission_map = {"*": "connectors.manage"}

    def post(self, request, account_id):
        return Response(test_connection(_account(request, account_id).id))


class DisconnectView(GrowthAPIView):
    permission_map = {"*": "connectors.manage"}

    def post(self, request, account_id):
        acc = _account(request, account_id)
        fetch_one("UPDATE public.tenant_connector_credentials SET deleted_at = now() WHERE account_id = %s AND deleted_at IS NULL RETURNING 1", [acc.id])
        set_status(acc.id, "disconnected")
        fetch_one("INSERT INTO public.connector_audit_logs (tenant_id, account_id, actor_user_id, action) VALUES (%s,%s,%s,'disconnect') RETURNING id",
                  [acc.tenant_id, acc.id, request.user.id])
        record_audit("connector.disconnected", "integrations", entity_type="tenant_connector_accounts", entity_id=acc.id)
        return Response({"status": "disconnected"})


class OAuthStartView(GrowthAPIView):
    permission_map = {"*": "connectors.manage"}

    def post(self, request, account_id):
        return Response({"authorization_url": oauth_start(_account(request, account_id).id)})


class OAuthCallbackView(PublicWebhookView):
    """Provider redirects here; the signed, expiring `state` identifies tenant + account."""
    def get(self, request):
        self.platform_scope(request)
        if request.query_params.get("error"):
            return HttpResponseRedirect(f"{settings.GROWTH['FRONTEND_URL']}/?oauth=error")
        tenant_id, back = oauth_callback(request.query_params.get("code", ""), request.query_params.get("state", ""))
        sep = "&" if back and "?" in back else "?"
        return HttpResponseRedirect(f"{settings.GROWTH['FRONTEND_URL']}{back}{sep}oauth=success" if back
                                    else f"{settings.GROWTH['FRONTEND_URL']}/t/{tenant_id}/connectors?oauth=success")


class ConnectorStatusView(GrowthAPIView):
    permission_map = {"GET": "connectors.read"}

    def get(self, request):
        return Response(fetch_all_dict(
            """SELECT a.id, p.code AS provider, p.name AS provider_name, p.category, p.auth_type, p.docs_status, a.display_name,
                      a.status, a.last_test_at, a.last_test_status, a.last_error, a.connected_at, a.settings,
                      (SELECT masked_hint FROM public.tenant_connector_credentials c WHERE c.account_id = a.id AND c.deleted_at IS NULL
                        ORDER BY c.created_at DESC LIMIT 1) AS credential_hint
                 FROM public.tenant_connector_accounts a JOIN public.connector_providers p ON p.id = a.provider_id
                WHERE a.tenant_id = %s AND a.deleted_at IS NULL ORDER BY p.category, p.name""", [request.tenant.tenant_id]))


class PilotOAuthClientView(GrowthAPIView):
    platform_scoped = True

    def post(self, request):
        code, client_id, secret = request.data.get("provider_code"), request.data.get("client_id"), request.data.get("client_secret")
        if not (code and client_id and secret):
            raise BusinessError("provider_code, client_id and client_secret are required", "invalid")
        fetch_one("""INSERT INTO public.connector_global_configurations (provider_id, client_id, client_secret_ciphertext, redirect_uri)
                     SELECT id, %s, %s, %s FROM public.connector_providers WHERE code = %s
                     ON CONFLICT (provider_id) WHERE deleted_at IS NULL DO UPDATE SET client_id = EXCLUDED.client_id,
                       client_secret_ciphertext = EXCLUDED.client_secret_ciphertext RETURNING id""",
                  [client_id, encrypt_json({"client_secret": secret}), f"{settings.PUBLIC_API_URL}/api/v1/connectors/oauth/callback", code])
        record_audit("pilot.oauth_client_configured", "integrations", after={"provider": code})
        return Response({"status": "configured"})
