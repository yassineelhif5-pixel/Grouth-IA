# Growth IA

Plateforme SaaS multi-tenant **Growth IA** : base Supabase entièrement traçable, backend Django modulaire, frontend React/TypeScript (console PILOTE + espace tenant), Celery/Redis, Docker et CI — avec les modules métier PROMPT 2 (SEO, GEO, contenus, opportunités, prospection, e-mail, WhatsApp, CRM, programmations, workflows, THOR, reporting).

| | |
|---|---|
| Base | Supabase PostgreSQL 17 — 291 tables (315 avec partitions), RLS sur 100 % des tables, historique versionné automatique |
| Backend | Python 3.12 · Django 5.2 · DRF · Celery · Redis |
| Frontend | React 19 · TypeScript strict · Vite · TanStack Query · Zustand · RHF + Zod · Mantine |
| Auth | Supabase Auth (e-mail, vérification, reset, MFA, SSO, invitations) validé côté Django |

## Démarrage rapide

```bash
cp .env.example .env            # renseigner Supabase, Redis, secrets
docker compose run --rm migrate # applique database/migrations via Django (idempotent)
docker compose up -d            # backend :8000, frontend :8080, worker, beat, redis
```

Développement sans Docker :

```bash
cd backend && pip install -r requirements/dev.txt && DB_ROLE= python manage.py migrate && python manage.py runserver
cd frontend && npm install && npm run dev
```

## Modules métier
| Domaine | Modules | Doc |
|---|---|---|
| Acquisition | Produits & onboarding, SEO, GEO, Content Factory, Page Builder, Social Publisher, Video Studio | [Produits](docs/modules/PRODUCTS.md) · [SEO](docs/modules/SEO.md) · [GEO](docs/modules/GEO.md) · [Contenus](docs/modules/CONTENT_FACTORY.md) |
| Détection | Opportunity Hunter, Social Opportunity Hunter, Growth Intelligence | [Opportunités](docs/modules/OPPORTUNITY_HUNTER.md) |
| Vente | Smart Prospect, Email Center, WhatsApp, CRM | [Prospection](docs/modules/SMART_PROSPECT.md) · [E-mail](docs/modules/EMAIL_CENTER.md) · [CRM](docs/modules/CRM.md) |
| Automatisation | Multi-Scheduler, Workflow Engine, modes de croissance & approbations, THOR | [Programmations](docs/modules/SCHEDULER.md) · [THOR](docs/modules/THOR.md) |
| Plateforme | Connecteurs, fournisseurs IA, reporting PDF/XLSX/CSV, console PILOTE, System Health, licences Stripe | [Connecteurs](docs/integrations/CONNECTORS.md) · [Réception e-mail](docs/integrations/EMAIL_RECEIVING.md) |

Règles communes : aucun appel externe depuis le navigateur, secrets chiffrés côté backend, connecteurs jamais simulés (`tested` seulement après un appel réel), contenus entrants traités comme non fiables, actions sortantes soumises au mode de croissance du tenant.

## Structure

```
backend/      Django (config/, apps/<module>/, tests/)
frontend/     React + TypeScript (src/app, components, layouts, pages, features, services, hooks, stores, types, utils)
database/     schema/ (DSL source de vérité + générateur), migrations/, tests/, schema.sql
docs/         architecture, database, security, traceability, deployment, operations
infrastructure/ docker, monitoring, scripts (db_local.sh)
```

## Traçabilité (4 niveaux)
Aucun historique parallèle : tous les modules utilisent les mêmes tables — voir [historique métier](docs/traceability/BUSINESS_HISTORY.md), [exécutions](docs/traceability/EXECUTION_TRACEABILITY.md), [IA](docs/traceability/AI_TRACEABILITY.md), [e-mails](docs/traceability/EMAIL_HISTORY.md).

1. Données métier · 2. `entity_history` (trigger, même transaction) · 3. `audit_events` + `activity_events` · 4. `execution_logs` + erreurs. Un `correlation_id` relie l'action frontend, la requête API, la transaction, la tâche Celery et le résultat — voir [docs/traceability](docs/traceability/TRACEABILITY_ARCHITECTURE.md).

## Tests
```bash
PGURL=postgresql://postgres@localhost/growth_test infrastructure/scripts/db_local.sh --tests   # SQL (RLS, isolation, historique)
cd backend && pytest                                  # unitaires
cd backend && RUN_INTEGRATION=1 pytest                # API + PostgreSQL + 10 parcours de bout en bout (PROMPT 2)
cd frontend && npm test
```

## Documentation
[Architecture](docs/architecture/ARCHITECTURE.md) · [Schéma](docs/database/SCHEMA_OVERVIEW.md) · [Dictionnaire](docs/database/DATA_DICTIONARY.md) · [ERD](docs/database/ERD.md) · [RLS](docs/database/RLS_POLICIES.md) · [Migrations](docs/database/MIGRATIONS.md) · [Index](docs/database/INDEX_STRATEGY.md) · [Sécurité](docs/security/SECURITY.md) · [Déploiement](docs/deployment/DEPLOYMENT.md) · [Exploitation](docs/operations/OPERATIONS.md) · [Audit initial](docs/AUDIT_INITIAL.md) · [Rapport PROMPT 1](docs/FINAL_REPORT.md) · [Rapport PROMPT 2](docs/PROMPT2_REPORT.md)
