"""Connector catalogue: how each provider is connected, so the UI can offer a one-click
"Se connecter avec …" (OAuth) or a guided form instead of raw JSON.

Two connection methods:
  - oauth      : the tenant authorizes Growth IA on the provider (needs the PILOTE to register the OAuth app once per family).
  - api_key    : the tenant pastes credentials into named, documented fields (no JSON).
A provider can offer both (e.g. GitHub: OAuth or a fine-grained token).

Nothing here holds a secret. Field specs only describe what to ask and where to find it.
"""
from __future__ import annotations

from apps.core.db import fetch_all_dict

from .providers import PROVIDER_OAUTH

# OAuth families: one OAuth app (client id/secret) registered by the PILOTE serves every provider of the family.
FAMILIES: dict[str, dict] = {
    "google": {
        "label": "Google",
        "console": "https://console.cloud.google.com/apis/credentials",
        "steps": ["Google Cloud Console → APIs & Services → Identifiants → Créer des identifiants → ID client OAuth (type Application Web).",
                  "Collez l'URI de redirection ci-dessous dans « URIs de redirection autorisés ».",
                  "Activez les API utilisées (Gmail, Analytics Data, Search Console) et renseignez l'écran de consentement.",
                  "Copiez l'ID client et le secret client ci-dessous."],
    },
    "microsoft": {
        "label": "Microsoft",
        "console": "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        "steps": ["Entra (Azure AD) → Inscriptions d'applications → Nouvelle inscription.",
                  "Ajoutez l'URI de redirection ci-dessous (plateforme Web).",
                  "Certificats & secrets → Nouveau secret client.",
                  "Copiez l'ID d'application (client) et la valeur du secret."],
    },
    "github": {
        "label": "GitHub",
        "console": "https://github.com/settings/developers",
        "steps": ["GitHub → Settings → Developer settings → OAuth Apps → New OAuth App.",
                  "Collez l'URL de rappel (callback) ci-dessous dans « Authorization callback URL ».",
                  "Copiez le Client ID, puis générez et copiez un Client secret."],
    },
    "linkedin": {"label": "LinkedIn", "console": "https://www.linkedin.com/developers/apps",
                 "steps": ["LinkedIn Developers → Create app.", "Onglet Auth : ajoutez l'URL de redirection ci-dessous.",
                           "Copiez le Client ID et le Client Secret."]},
    "facebook": {"label": "Meta (Facebook / Instagram)", "console": "https://developers.facebook.com/apps",
                 "steps": ["Meta for Developers → Créer une app (type Business).", "Produit « Connexion Facebook » : ajoutez l'URI de redirection ci-dessous.",
                           "Paramètres → Général : copiez l'identifiant et la clé secrète de l'app."]},
    "hubspot": {"label": "HubSpot", "console": "https://developers.hubspot.com/",
                "steps": ["HubSpot developer account → Apps → Create app.", "Auth : ajoutez l'URL de redirection ci-dessous.",
                          "Copiez le Client ID et le Client secret."]},
    "reddit": {"label": "Reddit", "console": "https://www.reddit.com/prefs/apps",
               "steps": ["Reddit → preferences → apps → create another app (type web app).", "Collez l'URI de redirection ci-dessous.",
                         "Copiez l'identifiant (sous le nom) et le secret."]},
}


def provider_family(code: str) -> str | None:
    return PROVIDER_OAUTH[code][0] if code in PROVIDER_OAUTH else None


def _field(name, label, *, secret=False, type="text", required=True, help="", placeholder=""):
    return {"name": name, "label": label, "secret": secret, "type": type, "required": required, "help": help, "placeholder": placeholder}


# Guided forms for the implemented api_key / basic providers (field names match the connection tests exactly).
_U = _field("username", "Utilisateur", help="")
_P = _field("password", "Mot de passe", secret=True, type="password")
FORMS: dict[str, dict] = {
    "smtp": {"settings": [_field("host", "Serveur SMTP", placeholder="smtp.exemple.com"), _field("port", "Port", type="number", required=False, placeholder="587")],
             "secrets": [_U, _P]},
    "imap": {"settings": [_field("host", "Serveur IMAP", placeholder="imap.exemple.com"), _field("port", "Port", type="number", required=False, placeholder="993")],
             "secrets": [_U, _P]},
    "sendgrid": {"secrets": [_field("api_key", "Clé API SendGrid", secret=True, help="SendGrid → Settings → API Keys (Full Access).")]},
    "resend": {"secrets": [_field("api_key", "Clé API Resend", secret=True, help="resend.com → API Keys.")]},
    "brevo": {"secrets": [_field("api_key", "Clé API Brevo", secret=True, help="Brevo → SMTP & API → Clés API.")]},
    "postmark": {"secrets": [_field("api_key", "Jeton serveur Postmark", secret=True, help="Postmark → votre serveur → API Tokens.")]},
    "mailgun": {"settings": [_field("domain", "Domaine d'envoi", placeholder="mg.exemple.com"),
                             _field("base_url", "Région API", required=False, placeholder="https://api.mailgun.net (ou .eu)")],
                "secrets": [_field("api_key", "Clé API Mailgun", secret=True, help="Mailgun → Settings → API Keys (Private API key).")]},
    "stripe": {"secrets": [_field("api_key", "Clé secrète Stripe", secret=True, placeholder="sk_live_…", help="Stripe → Développeurs → Clés API → clé secrète.")]},
    "wordpress": {"settings": [_field("site_url", "Adresse du site", type="url", placeholder="https://votre-site.fr")],
                  "secrets": [_U, _field("application_password", "Mot de passe d'application", secret=True,
                                         help="WordPress → Utilisateurs → Profil → Mots de passe d'application.")]},
    "ghost": {"settings": [_field("site_url", "Adresse du site", type="url", placeholder="https://votre-site.fr")],
              "secrets": [_field("admin_api_key", "Clé API Admin (id:secret)", secret=True, help="Ghost → Settings → Integrations → Add custom integration.")]},
    "rest_cms": {"settings": [_field("test_url", "URL de test (GET authentifié)", type="url", placeholder="https://api.exemple.com/me")],
                 "secrets": [_field("api_key", "Jeton Bearer", secret=True)]},
    "whatsapp_cloud": {"settings": [_field("phone_number_id", "Phone number ID", help="Meta → WhatsApp → API Setup.")],
                       "secrets": [_field("access_token", "Jeton d'accès", secret=True, help="Meta → WhatsApp → jeton permanent (System User).")]},
    "pagespeed": {"settings": [_field("test_url", "URL à tester par défaut", type="url", required=False, placeholder="https://votre-site.fr")],
                  "secrets": [_field("api_key", "Clé API Google", secret=True, help="Google Cloud Console → Identifiants → Clé API (API PageSpeed Insights activée).")]},
    "github": {"settings": [_field("repo", "Dépôt du site", required=False, placeholder="https://github.com/acme/site ou acme/site", help="Lien GitHub du dépôt ou propriétaire/nom. Facultatif ici ; requis pour la correction forcée.")],
               "secrets": [_field("token", "Jeton d'accès GitHub (fine-grained)", secret=True,
                                  help="GitHub → Settings → Developer settings → Fine-grained tokens, permissions Contents + Pull requests sur le dépôt.")]},
}


def _method(code: str, auth_type: str, has_form: bool, oauth_ready: bool) -> str:
    if code == "github":
        return "oauth_or_key"
    if code in PROVIDER_OAUTH:
        return "oauth"
    if has_form:
        return "api_key"
    return "unsupported"


def catalog(tenant_id: str) -> dict:
    """Providers enriched with connection method, guided fields, OAuth availability and the tenant's current account."""
    providers = fetch_all_dict(
        """SELECT p.id, p.code, p.name, p.category, p.auth_type,
                  coalesce(auth.status, 'not_authorized') AS authorization_status,
                  acc.id AS account_id, acc.status AS account_status, acc.last_test_at, acc.last_error, acc.settings,
                  (SELECT masked_hint FROM public.tenant_connector_credentials c WHERE c.account_id = acc.id AND c.deleted_at IS NULL
                    ORDER BY c.created_at DESC LIMIT 1) AS credential_hint
             FROM public.connector_providers p
             LEFT JOIN public.tenant_connector_authorizations auth ON auth.provider_id = p.id AND auth.tenant_id = %s AND auth.deleted_at IS NULL
             LEFT JOIN LATERAL (SELECT * FROM public.tenant_connector_accounts a WHERE a.provider_id = p.id AND a.tenant_id = %s
                                 AND a.deleted_at IS NULL ORDER BY a.created_at LIMIT 1) acc ON true
            WHERE p.is_enabled ORDER BY p.category, p.name""", [tenant_id, tenant_id])
    configured_families = _configured_families()
    out = []
    for p in providers:
        code = p["code"]
        family = provider_family(code)
        oauth_ready = bool(family and configured_families.get(family))
        form = FORMS.get(code)
        method = _method(code, p["auth_type"], bool(form), oauth_ready)
        fam = FAMILIES.get(family or "")
        out.append({
            "code": code, "name": p["name"], "category": p["category"], "method": method,
            "oauth_available": oauth_ready, "oauth_family": family, "family_label": fam["label"] if fam else None,
            "authorization_status": p["authorization_status"],
            "fields": form.get("secrets", []) if form else [], "settings_fields": form.get("settings", []) if form else [],
            "help_url": (fam or {}).get("console"),
            "account": None if not p["account_id"] else {
                "id": str(p["account_id"]), "status": p["account_status"], "last_test_at": p["last_test_at"],
                "last_error": p["last_error"], "settings": p["settings"], "credential_hint": p["credential_hint"]},
        })
    return {"providers": out, "redirect_uri": _redirect_uri(),
            "note": "Se connecter avec le fournisseur (OAuth) quand c'est proposé, sinon coller les informations dans le formulaire guidé."}


def _configured_families() -> dict[str, bool]:
    rows = fetch_all_dict(
        """SELECT p.code FROM public.connector_global_configurations g JOIN public.connector_providers p ON p.id = g.provider_id
            WHERE g.is_enabled AND g.client_id IS NOT NULL AND g.deleted_at IS NULL""")
    out: dict[str, bool] = {}
    for r in rows:
        fam = provider_family(r["code"]) or r["code"]
        out[fam] = True
    return out


def _redirect_uri() -> str:
    from .providers import redirect_uri
    return redirect_uri()


def pilot_oauth_families() -> list[dict]:
    """For the PILOTE: each OAuth family, whether its app is configured, and the redirect URI to paste into the provider."""
    configured = _configured_families()
    return [{"family": fam, "label": meta["label"], "console": meta["console"], "steps": meta["steps"],
             "configured": bool(configured.get(fam)), "redirect_uri": _redirect_uri(),
             "providers": sorted(c for c, (f, _s) in PROVIDER_OAUTH.items() if f == fam) or [fam]}
            for fam, meta in FAMILIES.items()]
