# Historique métier

PROMPT 2 n'ajoute **aucun système d'historique parallèle** : tous les modules réutilisent les tables de traçabilité de PROMPT 1.

| Niveau | Table | Écrit par | Contenu |
|---|---|---|---|
| Version d'entité | `entity_history` | trigger `app.tg_entity_history` (même transaction) | avant/après, champs modifiés, acteur, `correlation_id`, motif |
| Audit | `audit_events` | `record_audit()` | action métier, statut, avant/après expurgés |
| Activité | `activity_events` | `record_activity()` | fil lisible par l'utilisateur (« Audit SEO lancé… ») |
| Exécution | `execution_logs` | `track_execution()` (connexion `logs` séparée) | tâche, durée, entrée/sortie résumées, erreur |

## Types de tables (DSL `database/schema/dsl.py`)
- `biz` / `conf` / `gbiz` : versionnées automatiquement ; suppression logique (`deleted_at`).
- `log` / `glog` : append-only (UPDATE/DELETE refusés, correction via `app.correct_log_entry`).
- `run` (nouveau, PROMPT 2) : exécutions dont le **statut évolue** (`queued → running → succeeded/failed`) ; UPDATE autorisé, **DELETE interdit** (trigger `app.tg_append_only`), `app_backend` n'a pas le droit DELETE. 15 tables : `website_scans`, `seo_audits`, `geo_audits`, `ai_search_runs`, `content_generation_jobs`, `video_generation_jobs`, `video_render_jobs`, `connector_sync_runs`, `scheduler_execution_runs`, `scheduler_execution_steps`, `growth_workflow_executions`, `growth_workflow_execution_steps`, `email_sync_runs`, `notification_deliveries`, `email_webhook_events`.

## Onglet Historique
Chaque page module du frontend (`ModulePage.tsx`) propose un onglet *Historique* (`HistoryCentre` filtré par module/entité) alimenté par `/api/v1/history` : versions, audit et activité, avec filtre par `correlation_id`.

## Approbations
`approval_requests` (biz) : demande, décideur, décision, motif, exécution du handler après approbation — chaque transition est versionnée et auditée.
