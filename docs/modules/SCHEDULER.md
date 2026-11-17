# Multi-Scheduler & Workflow Engine

Code : `backend/apps/scheduler/` (`engine.py`, `tasks.py`, `views.py`) · Front : *Programmations*, *Workflows*.

## Programmations (`/api/v1/schedulers`)
- Catégories : `seo, geo, articles, pages, social, videos, opportunities, social_monitoring, prospects, crm, reporting, intelligence, agents`.
- Fréquences : `hourly, every_x_hours, daily, weekly, monthly, cron, event, conditional` ; fuseau horaire par programmation ; `next_run_at` calculé (croniter).
- Modes : `automatic`, `approval`, `analysis_only` (borné par le mode de croissance du tenant).
- Actions : `run` (manuel), `control` (pause/reprise/annulation), `runs` (exécutions et étapes).
- `scheduler.dispatch` (beat, chaque minute) verrouille et lance les programmations dues ; une exécution déjà en cours → la nouvelle est `cancelled` (pas de chevauchement).
- `scheduler.recover` : les runs bloqués > 2 h passent en `failed (worker lost)` et sont relancés.

## Workflows (`/api/v1/workflows`)
- Définition JSON validée : nœuds `seo_scan, detect_opportunities, generate_content, social_signals, geo_optimize, qualify_prospects, publish_content, notify, measure, condition, approval, wait`.
- Chaque nœud est une étape persistée (`growth_workflow_execution_steps`) avec tentative, clé d'idempotence, sortie.
- **Retry avec backoff** exponentiel (60 s × 2ⁿ) pour les erreurs techniques ; erreurs métier → échec immédiat.
- **Nœud d'approbation** : crée une `approval_requests` ; l'exécution reprend après approbation.
- **Reprise idempotente** : une étape `succeeded` n'est jamais rejouée.

## Tables
`tenant_schedulers`, `scheduler_execution_runs`/`_steps` (*run*), `growth_workflow_definitions`, `growth_workflow_executions`/`_steps` (*run*).
