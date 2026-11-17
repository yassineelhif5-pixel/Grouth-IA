# Sécurité

## Authentification
- **Supabase Auth** : e-mail/mot de passe, vérification e-mail, reset, MFA TOTP, SSO (SAML/OIDC via `tenant_sso_configurations`), invitations.
- Django valide **cryptographiquement** chaque JWT : clés asymétriques via JWKS (`/auth/v1/.well-known/jwks.json`, ES256/RS256) ou secret HS256 historique ; `aud=authenticated`, `iss=<SUPABASE_URL>/auth/v1`, `exp/iat/sub` requis, `role=authenticated`.
- **PILOTE** : rôle plateforme `PILOTE` dans `user_profiles` + niveau d'assurance `aal2` (MFA) exigé côté API et côté UI.

## Autorisation (défense en profondeur)
1. Django : appartenance au tenant vérifiée en base à chaque requête, permission (`app.has_permission`), module autorisé par la licence, quotas.
2. PostgreSQL : RLS pour `authenticated` **et** pour `app_backend` ; FK composites `(tenant_id, id)` ; `tenant_id` et `id` immuables (trigger).
3. Celery : le contexte (utilisateur, tenant) est restauré et réappliqué en base ; les tâches globales n'obtiennent le scope plateforme qu'explicitement.

## Secrets
- Jamais dans le dépôt (`.gitignore`, `.env.example` sans valeurs).
- Credentials de connecteurs et clés fournisseurs IA : **Supabase Vault** — PostgreSQL ne stocke que l'identifiant Vault et un indice masqué (`••••abcd`).
- Colonnes marquées `secret` dans le DSL : exclues de `entity_history` (trigger), retirées des sérialiseurs API, masquées dans `audit_events` (`redact`).
- Logs et erreurs : `redact_text` supprime JWT et en-têtes Bearer/Basic.
- Jetons d'invitation : seul le SHA-256 est stocké ; le jeton ne transite que dans l'e-mail.

## Journaux
- `audit_events`, `entity_history`, `activity_events`, `execution_logs` et autres journaux sont **append-only** : `UPDATE/DELETE` bloqués par trigger (même pour le propriétaire) et non accordés à `app_backend`.
- Correction exceptionnelle : `app.correct_log_entry()` (scope plateforme + motif obligatoire), elle-même tracée dans `audit_log_corrections` et `audit_events`.

## API
- Throttling DRF (utilisateur/anonyme), CORS restreint, HSTS, `X-Frame-Options: DENY`, `nosniff`.
- Erreurs uniformes sans fuite d'information (un tenant étranger renvoie 404) ; rollback systématique des écritures partielles.
- Export CSV protégé contre l'injection de formules.

## Points d'attention production
- Créer un rôle LOGIN dédié `growth_backend` (membre de `app_backend` uniquement) plutôt que d'utiliser `postgres` pour l'application.
- Activer la protection contre les mots de passe compromis et le MFA dans Supabase Auth.
- Rotation régulière de `SUPABASE_SERVICE_ROLE_KEY` et `DJANGO_SECRET_KEY`.
