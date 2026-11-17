# Déploiement

## Prérequis
- Projet Supabase (ici `nhjhmctxbrcwnkuojwzt`, eu-west-1, PostgreSQL 17) avec extensions `pgcrypto`, `pg_trgm`, `vector`.
- Redis 7, Python 3.12, Node 22, Docker.

## Étapes
1. `cp .env.example .env` et renseigner les valeurs (Supabase → Project Settings → API / Database).
2. Base : `docker compose run --rm migrate` (équivaut à `DB_ROLE= python manage.py migrate`). Idempotent : sans effet sur un projet déjà migré.
3. Rôle applicatif de production (recommandé) :
   ```sql
   CREATE ROLE growth_backend LOGIN PASSWORD '<secret>' NOINHERIT;
   GRANT app_backend TO growth_backend;
   ```
   puis `DB_USER=growth_backend`, `DB_ROLE=app_backend`.
4. Premier PILOTE : créer l'utilisateur via Supabase Auth, puis
   `UPDATE public.user_profiles SET platform_role_code = 'PILOTE' WHERE email = '<email>';` (insérer le profil s'il n'existe pas) — l'action est historisée. Activer le MFA à la première connexion (`/mfa`).
5. `docker compose up -d backend worker beat frontend`.
6. Vérifier : `GET /api/v1/health/ready`, puis PILOTE → System Health → « Lancer les tests ».

## Variables PROMPT 2
| Variable | Rôle |
|---|---|
| `SECRETS_ENCRYPTION_KEY` | clé(s) Fernet (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) — **obligatoire** |
| `PUBLIC_API_URL` | URL publique de l'API (callbacks OAuth, URLs de webhooks) |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | paiement des plans (webhook `POST /api/v1/webhooks/stripe`) |
| `CRAWLER_USER_AGENT`, `CRAWLER_MAX_PAGES`, `CRAWLER_DELAY_SECONDS` | crawler SEO |
| `ATTACHMENT_MAX_BYTES` | taille max des pièces jointes reçues |

Clés IA, clients OAuth et identifiants de connecteurs **ne sont pas des variables d'environnement** : ils sont saisis dans la console (PILOTE → IA / OAuth, tenant → Connecteurs) et chiffrés en base.

## Mise à niveau PROMPT 1 → PROMPT 2
Migrations **additives uniquement** (`ADD COLUMN IF NOT EXISTS`, nouvelles tables, contraintes CHECK élargies, `0011_prompt2_reference_data.sql` en `ON CONFLICT DO NOTHING`) : aucune table ni donnée supprimée. Appliquées sur Supabase le 17/11/2026 puis tests SQL `10_*` et `20_*` exécutés avec succès (rollback).

## Supabase Auth
- URL de redirection : `<FRONTEND_URL>/onboarding`, `<FRONTEND_URL>/reset-password`.
- Activer : confirmation e-mail, MFA TOTP, protection des mots de passe compromis.
- SSO entreprise : configurer le fournisseur dans Supabase puis l'associer au tenant (`tenant_sso_configurations`, `tenant_sso_group_mappings`).

## CI/CD
`.github/workflows/ci.yml` : dérive du schéma, migrations ×2, tests SQL (RLS/isolation/traçabilité), lint/types/sécurité Python, tests unitaires + intégration, lint/typecheck/tests/build frontend, build Docker. **Aucun déploiement si un contrôle échoue** (brancher l'étape de déploiement sur `needs: [docker]` et la protection de branche `main`).
