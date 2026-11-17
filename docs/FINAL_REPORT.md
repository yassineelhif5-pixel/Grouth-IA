# Rapport final — PROMPT 1 (socle technique Growth IA)

## Chiffres réels (mesurés sur le projet Supabase `nhjhmctxbrcwnkuojwzt`)

| Élément | Valeur |
|---|---|
| Tables | **276** (+ 24 partitions mensuelles/défaut) |
| Clés étrangères | **857** (dont FK composites `(tenant_id, id)` entre tables tenant) |
| Index | **1 550** sur les tables (+ index des partitions) |
| Politiques RLS | **825** — RLS active sur 100 % des tables et partitions |
| Triggers de traçabilité | 743 |
| Fonctions SQL (`app`) | 28 |
| Migrations SQL du dépôt | 10 fichiers, toutes appliquées sur Supabase depuis le dépôt (contrôle md5) |
| Tables isolées par tenant / versionnées / append-only | 252 / 143 / 110 |

## Tests exécutés

| Suite | Où | Résultat |
|---|---|---|
| SQL sécurité & traçabilité (45 assertions : RLS, isolation A/B, historique, secrets, immutabilité, FK composites, DEMO, quotas, rétention, licences) | PostgreSQL 16 local + **PostgreSQL 17 en CI** | **45/45 réussis** |
| Même suite | **Projet Supabase réel** (transaction annulée, 0 donnée laissée) | **réussie** |
| Idempotence (toutes les migrations appliquées 2 fois) | CI | réussie |
| Backend : 9 tests unitaires + 8 tests d'intégration API (JWT, inscription DEMO unique, en-tête tenant non fiable, isolation produits/historique, versioning & conflit de version, quota DEMO 3 schedulers, suppression/restauration, console PILOTE + suspension auditée, persistance après « redémarrage ») | CI GitHub Actions (Django 5.2 + PostgreSQL 17 + Redis) | **17/17 réussis**, couverture 91 % |
| Backend : ruff, bandit, pip-audit, `manage.py migrate` | CI | réussis (0 vulnérabilité connue) |
| Frontend : eslint, typecheck strict, vitest (6 tests), build Vite, npm audit | CI | **réussis** (0 vulnérabilité) |
| Build Docker backend + frontend | CI | réussi |

Tests échoués : **0**. Le pipeline CI complet est vert sur `main`.

## Éléments bloqués / à compléter
- E-mail : envoi via SMTP configurable ; sans `EMAIL_HOST`, les livraisons sont enregistrées en échec `not_configured` (jamais perdues silencieusement).
- Connecteurs : catalogue, autorisations, comptes, santé et audit en place ; les intégrations propres à chaque fournisseur (OAuth Google, HubSpot…) restent à implémenter dans les prochains modules.
- Clés Supabase (`anon`, `service_role`, secret JWT) et SMTP non renseignées : à placer dans `.env` (voir `.env.example`). L'application n'a donc pas encore été déployée sur un serveur.
- Premier compte PILOTE à désigner (voir `docs/deployment/DEPLOYMENT.md`).
- Tests navigateur de bout en bout (Playwright) et tests MFA/SSO réels avec Supabase Auth : à ajouter quand l'environnement de recette sera configuré.

## Historisation testée
INSERT → UPDATE → mise à jour sans changement (pas de version) → SOFT_DELETE → RESTORE ; auteur, motif et correlation_id provenant du contexte Django ; avant/après et champs modifiés ; secrets exclus ; journaux non modifiables même par le propriétaire ; correction administrative auditée ; purge uniquement sous politique explicite ; isolation des historiques entre tenants (navigateur et backend).

## État
- **Supabase** : schéma complet appliqué, testé, advisors sécurité sans alerte bloquante (seule info : partitions sans politique propre, voulu — accès via la table parente). Extension temporaire `http` utilisée pour le chargement des migrations : supprimée.
- **Backend** : monolithe Django modulaire (27 apps), API `/api/v1` (OpenAPI `/api/v1/docs`), JWT Supabase, multi-tenant, licences, permissions, console PILOTE, centre d'historique, System Health, Celery (files, retry, dead letter, idempotence, contexte propagé).
- **Frontend** : React 19 + TypeScript strict + Vite, Router, TanStack Query, Zustand, React Hook Form + Zod, Mantine ; FR/EN, clair/sombre ; console PILOTE, espace tenant, centre d'historique, System Health.
- **GitHub** : `main` à jour, sans secret, CI verte (SQL, backend, frontend, Docker).
