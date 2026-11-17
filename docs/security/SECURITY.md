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
- Credentials de connecteurs, jetons OAuth et clés fournisseurs IA : **chiffrés côté backend** (Fernet/`MultiFernet`, clé `SECRETS_ENCRYPTION_KEY` hors base, rotation possible) dans des colonnes `*_ciphertext` ; l'API ne renvoie qu'un indice masqué (`••••abcd`). Les colonnes PROMPT 1 prévues pour Supabase Vault restent disponibles.
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

## Intégrations et IA (PROMPT 2)
- **Aucun appel externe depuis React** : passerelle d'intégration et passerelle IA côté backend uniquement.
- Webhooks (Stripe, e-mail, WhatsApp) : signature vérifiée à temps constant, fenêtre de fraîcheur, anti-rejeu `idempotency_keys` ; le tenant est déduit de la ressource en base, **jamais d'un `tenant_id` envoyé par le client**.
- OAuth : `state` signé et lié au compte, aucune redirection ouverte.
- Contenus entrants (e-mails, pages web, documents, signaux sociaux) = **données non fiables** : encapsulés `<untrusted_data>`, ne peuvent modifier ni les instructions ni les permissions de THOR ; HTML jamais exécuté côté UI ; XML parsé avec `defusedxml`.
- THOR : outils filtrés par licence **et** permission, outil inconnu refusé et journalisé, aucun envoi automatique d'e-mail sans double autorisation PILOTE + tenant.
- Modes de croissance : toute action sortante (envoi, publication, campagne) passe par `gate()` → exécution, approbation ou analyse seule.
- Conformité prospection : désabonnement traité immédiatement, listes de suppression vérifiées à chaque envoi, consentement exigé ; WhatsApp : opt-in, STOP, fenêtre de 24 h, modèles approuvés.
- Crawler : respect de `robots.txt`, user-agent identifiable, hôte unique, pages bornées ; plateformes tierces uniquement via API officielles.
- Statuts de connecteurs **jamais simulés** : `tested` uniquement après un appel réel réussi.

## Points d'attention production
- Créer un rôle LOGIN dédié `growth_backend` (membre de `app_backend` uniquement) plutôt que d'utiliser `postgres` pour l'application.
- Activer la protection contre les mots de passe compromis et le MFA dans Supabase Auth.
- Rotation régulière de `SUPABASE_SERVICE_ROLE_KEY`, `DJANGO_SECRET_KEY` et `SECRETS_ENCRYPTION_KEY`.
- `SECRETS_ENCRYPTION_KEY` perdue = identifiants de connecteurs irrécupérables : la sauvegarder dans un coffre distinct de la base.
