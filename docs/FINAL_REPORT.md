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
| SQL sécurité & traçabilité (45 assertions : RLS, isolation A/B, historique, secrets, immutabilité, FK composites, DEMO, quotas, rétention, licences) | PostgreSQL local (émulation Supabase) | **45/45 réussis** |
| Même suite | **Projet Supabase réel** (transaction annulée, aucune donnée laissée) | **réussie** |
| Idempotence (migrations appliquées 2 fois) | local | réussie |
| Python unitaires (contexte, corrélation, redaction) | local | **9/9 réussis** |
| Syntaxe Python (181 fichiers) / TypeScript (25 fichiers) | local | 0 erreur |
| Django intégration (8 tests API : JWT, isolation, versioning, quotas, PILOTE, persistance) | CI GitHub Actions | **écrits, non exécutés ici** |
| Frontend vitest (2 fichiers) + lint + typecheck + build | CI GitHub Actions | **écrits, non exécutés ici** |

Tests échoués : 0 parmi les tests exécutés.

## Éléments bloqués / non vérifiés
- **Django et React n'ont pas été exécutés** dans cette session (installation pip/npm impossible). Le code est complet et vérifié syntaxiquement ; la CI (`.github/workflows/ci.yml`) l'installe, le lance et le teste. → À vérifier au premier run de la CI ; des corrections mineures peuvent être nécessaires.
- Docker non construit ici (même raison) — build inclus dans la CI.
- E-mail : envoi via SMTP configurable ; sans `EMAIL_HOST`, les livraisons sont enregistrées en échec `not_configured` (jamais perdues silencieusement).
- Connecteurs : catalogue, autorisations, comptes, santé et audit en place ; les intégrations propres à chaque fournisseur (OAuth Google, HubSpot…) restent à implémenter dans les prochains modules.
- Clés Supabase (`anon`, `service_role`, secret JWT) non renseignées : à placer dans `.env` (voir `.env.example`).
- Premier compte PILOTE à désigner (voir `docs/deployment/DEPLOYMENT.md`).

## Historisation testée
INSERT → UPDATE → mise à jour sans changement (pas de version) → SOFT_DELETE → RESTORE ; auteur, motif et correlation_id provenant du contexte Django ; avant/après et champs modifiés ; secrets exclus ; journaux non modifiables même par le propriétaire ; correction administrative auditée ; purge uniquement sous politique explicite ; isolation des historiques entre tenants (navigateur et backend).

## État
- **Supabase** : schéma complet appliqué, testé, advisors sécurité sans alerte bloquante (seule info : partitions sans politique propre, voulu — accès via la table parente). Extension temporaire `http` utilisée pour le chargement des migrations : supprimée.
- **Backend** : monolithe Django modulaire (27 apps), API `/api/v1` (OpenAPI `/api/v1/docs`), JWT Supabase, multi-tenant, licences, permissions, console PILOTE, centre d'historique, System Health, Celery (files, retry, dead letter, idempotence, contexte propagé).
- **Frontend** : React 19 + TypeScript strict + Vite, Router, TanStack Query, Zustand, React Hook Form + Zod, Mantine ; FR/EN, clair/sombre ; console PILOTE, espace tenant, centre d'historique, System Health.
- **GitHub** : `main` à jour, sans secret.
