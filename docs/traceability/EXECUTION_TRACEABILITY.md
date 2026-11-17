# Traçabilité des exécutions

## Chaîne de corrélation
Requête API (`X-Request-ID`, `X-Correlation-ID`) → GUC PostgreSQL (`app.set_context`) → triggers d'historique → `delay_traced()` (contexte dans les en-têtes Celery) → `TracedTask` → `execution_logs` → résultats métier. Le même `correlation_id` permet de reconstituer toute la chaîne.

## TracedTask (`apps/observability/tasks_base.py`)
- Restaure utilisateur, tenant, corrélation ; applique le contexte en base **au niveau session** (la tâche gère ses propres transactions : un statut d'échec n'est jamais annulé avec le travail).
- Persiste chaque exécution via `track_execution` sur la connexion `logs` (survit à un rollback métier).
- Idempotence optionnelle (`idempotency_keys`).
- En exécution imbriquée/eager, le contexte de l'appelant est restauré ensuite : local à la transaction dans une requête, au niveau session hors transaction.
- Tâches globales : `run_in_platform_scope` ; boucle par tenant : `run_in_tenant_scope`.

## Tables d'exécution métier (*run*)
`website_scans`, `seo_audits`, `geo_audits`, `ai_search_runs`, `content_generation_jobs`, `video_generation_jobs`, `video_render_jobs`, `connector_sync_runs`, `scheduler_execution_runs`, `scheduler_execution_steps`, `growth_workflow_executions`, `growth_workflow_execution_steps`, `email_sync_runs`, `notification_deliveries`, `email_webhook_events` — avec `execution_id` relié à `execution_logs`. Les publications (`content_publications`) et destinataires de campagne (`prospect_campaign_recipients`) sont versionnés (biz).

## Reprise
`scheduler.recover` : runs bloqués > 2 h → `failed (worker lost)` + relance ; workflows `running/queued` repris de façon idempotente (une étape réussie n'est jamais rejouée).
