# Connecteurs

Code : `backend/apps/integrations/` (`gateway.py`, `providers.py`, `views_v2.py`) · Front : *Connecteurs* (tenant), *PILOTE → Connecteurs / OAuth*.

## Principes
- **Aucun appel externe depuis React** : tout passe par la Secure Integration Gateway (`gateway.http`) — timeouts, retries avec backoff, journal des erreurs (`connector_error_logs`), événements d'usage (`connector_usage_events`).
- **Secrets chiffrés côté backend** (Fernet `MultiFernet`, clé `SECRETS_ENCRYPTION_KEY`, rotation possible) dans des colonnes `*_ciphertext`, exclues de l'historique, de l'audit et des réponses API. L'API ne renvoie qu'un indice masqué.
- **Jamais de connexion simulée** : un compte n'est `tested` qu'après un vrai appel réussi au fournisseur. Sans identifiants → `not_configured`. Fournisseur non implémenté → `pending_approval`.
- OAuth : `state` signé et lié au compte, jeton de rafraîchissement chiffré, renouvellement automatique. Les clients OAuth globaux (Google, Microsoft, LinkedIn, Facebook, HubSpot, Reddit) sont saisis par le PILOTE (`/api/v1/pilot/oauth-clients`).
- Webhooks : signature HMAC vérifiée, anti-rejeu (`claim_once`), tenant identifié par la ressource en base.

## API
`/api/v1/connectors` (catalogue), `/api/v1/connector-accounts` (comptes du tenant), `…/{id}/credentials`, `…/{id}/test`, `…/{id}/disconnect`, `…/{id}/oauth/start`, `/api/v1/connectors/oauth/callback`, `/api/v1/connectors/status`, `/api/v1/pilot/tenants/{id}/connectors`. Santé : tâche `integrations.check_connectors` → `connector_health_checks`.

## Statuts d'un compte
`not_configured` → `configured` (identifiants enregistrés) → `connected` (OAuth terminé) → `tested` (appel réel réussi) · `failed` (appel réel en échec, message stocké) · `pending_approval` (fournisseur non implémenté ou en attente d'agrément de la plateforme tierce).

## Fournisseurs avec test réel implémenté
| Catégorie | Fournisseurs | Test effectué |
|---|---|---|
| E-mail | SMTP, IMAP, Gmail / Google Workspace, Microsoft Graph / Outlook, SendGrid, Postmark, Mailgun, Resend, Brevo | connexion/authentification ou appel API de compte |
| CMS | WordPress (mot de passe d'application), Ghost (Admin API JWT), API REST générique | lecture authentifiée |
| Social | LinkedIn, Facebook Pages | profil / pages |
| Messagerie | WhatsApp Business Cloud API | lecture du numéro |
| Paiement | Stripe | solde du compte ; webhooks signés |
| SEO | PageSpeed Insights | analyse d'une URL |

## Fournisseurs catalogués sans test implémenté
Marqués `pending_approval` lors d'un test : Google Analytics, Google Search Console, HubSpot, Reddit (OAuth prévu, appels métier non branchés), Instagram, YouTube, TikTok, X, Pinterest (agrément de l'API requis), et `not_implemented` : Amazon SES, Telegram, Messenger, Twilio, Vonage, Shopify, Webflow, Drupal, Bing Webmaster, Clarity, Salesforce, Pipedrive, Zoho, Dynamics 365, Odoo, PayPal, Paddle, Mollie, S3, Azure Blob, OneDrive.

## Fournisseurs IA
OpenAI, Anthropic, Google (Gemini), Mistral, Azure OpenAI, Cohere, Groq, Ollama, Perplexity — clés chiffrées saisies par le PILOTE, modèles et **prix configurés par le PILOTE** (jamais supposés), routes par fonctionnalité (`ai_feature_routes`) avec priorité et fallback, budget mensuel par tenant.

## État en production
**Aucun identifiant de fournisseur n'a été fourni** : tous les connecteurs sont `Not Configured` sur l'instance Supabase. Les tests CI utilisent des réponses HTTP simulées (`responses`) et ne valent pas validation d'un fournisseur réel.
