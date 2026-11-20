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

## Vercel (site React + API Django)
Un seul projet Vercel sert le site (fichiers statiques `frontend/dist`) et l'API (`api/index.py`, fonction Python WSGI) sur la **même origine** : `/api/*` → Django, tout le reste → SPA.

| Fichier | Rôle |
|---|---|
| `vercel.json` | build du frontend, fonction Python (`maxDuration` 60 s), réécritures `/api/*` et SPA |
| `api/index.py` | point d'entrée WSGI (charge `backend/config`) |
| `requirements.txt` | dépendances de la fonction (copie de `backend/requirements/base.txt`, vérifiée en CI) |
| `.vercelignore` | exclut secrets (`.env*`, `.vercel-token`), environnements locaux, tests, docs |
| `infrastructure/vercel/vercel-env.ps1` | crée le projet si besoin et pousse les variables de `.env.vercel` (API Vercel, upsert, chiffrées, production + preview) |
| `infrastructure/vercel/vercel-deploy.ps1` | `vercel link` puis `vercel deploy --prod` via `npx` (sortie de la CLI fusionnée par `cmd`, compatible Windows PowerShell 5) |
| `infrastructure/vercel/vercel-status.ps1` | état des 5 derniers déploiements, domaines, nombre de variables et journal de build du dernier déploiement |

Variables (fichier local `.env.vercel`, jamais commité) : `DJANGO_SECRET_KEY` (propre à la prod), `DB_*` (pooler Supabase **mode session**, port 5432), `DB_ROLE=app_backend`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SECRETS_ENCRYPTION_KEY` (**la même** que celle qui a chiffré les identifiants en base), `REDIS_URL=memory://`, `CELERY_TASK_ALWAYS_EAGER=true`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_URL=/api/v1`. Le domaine de production est lu de `VERCEL_PROJECT_PRODUCTION_URL` (hôtes autorisés, CSRF, `FRONTEND_URL`, `PUBLIC_API_URL`).

Limites de l'hébergement serverless : pas de worker ni de Celery Beat (programmations, synchro e-mail, campagnes et sondes planifiées ne tournent pas d'elles-mêmes), traitements limités à 60 s par requête (audits SEO volumineux), cache et limitation de débit par instance. Pour ces fonctions, héberger l'API et les workers sur un serveur (Docker Compose) et ne garder que le site sur Vercel.

Supabase Auth : ajouter le domaine Vercel dans *Authentication → URL Configuration* (Site URL et Redirect URLs `https://<domaine>/onboarding`, `https://<domaine>/reset-password`).

## Tâches planifiées sans Celery Beat (Vercel)
Sur Vercel il n'y a ni worker ni Celery Beat (`REDIS_URL=memory://`, `CELERY_TASK_ALWAYS_EAGER=true`). Les tâches
périodiques de `config/celery.py` (séances du Multi-Scheduler SEO / GEO / Smart Prospect, relances de campagnes,
synchronisation des boîtes e-mail, notifications programmées, expiration des essais, sondes System Health,
partitions, rétention) sont exécutées par `GET|POST /api/v1/internal/cron/tick`.

- Protection : en-tête `Authorization: Bearer <CRON_SECRET>` (variable `CRON_SECRET`, sans elle l'URL répond 503).
- Une seule exécution par période et par tâche (créneau réservé dans `idempotency_keys`), verrou consultatif
  PostgreSQL contre les appels simultanés, budget de 45 s (`CRON_TIME_BUDGET_SECONDS`) puis report au passage suivant.
- Vercel Cron (déclaré dans `vercel.json`) l'appelle une fois par jour : limite de l'offre gratuite. Pour un
  déclenchement toutes les 5 minutes, configurer un service de cron externe (ex. cron-job.org) sur
  `https://growthai.zirconai.fr/api/v1/internal/cron/tick` avec l'en-tête ci-dessus, ou passer à Vercel Pro.
- Avec un vrai worker + Celery Beat (Docker), cette URL est inutile : laisser `CRON_SECRET` vide.

## Offres payantes et essai
Offres `OFFRE_STARTER` (20 €), `OFFRE_PRO` (50 €), `OFFRE_PROFESSIONNELLE` (200 €), TTC mensuels (migration `0013`).
Essai gratuit de 48 h (migration `0014`). À la fin de l'essai l'espace passe en lecture seule (HTTP 402
`subscription_inactive` sur toute écriture) sauf le paiement ; le PILOTE n'est jamais bloqué. Le paiement Stripe
Checkout construit le prix depuis l'offre (pas d'identifiant de prix Stripe à créer) ; il suffit de
`STRIPE_SECRET_KEY` et `STRIPE_WEBHOOK_SECRET` (webhook `/api/v1/webhooks/stripe`, événements
`checkout.session.completed`, `invoice.payment_failed`, `customer.subscription.deleted`).
