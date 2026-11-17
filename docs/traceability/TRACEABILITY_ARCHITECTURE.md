# Architecture de traçabilité

PostgreSQL (Supabase) est la mémoire persistante : rien ne dépend du navigateur, de Redis, d'une session ou d'une tâche non persistée. Tout reste consultable après déconnexion, redémarrage ou redéploiement.

## Quatre niveaux complémentaires

| Niveau | Où | Écrit par | Contenu |
|---|---|---|---|
| 1 — Données métier | tables métier | services Django | état courant (`version_number`, `deleted_at`) |
| 2 — Historique des modifications | `entity_history` | **trigger** `app.tg_entity_history` | version, opération, avant/après, champs modifiés, auteur, motif, correlation |
| 3 — Journal d'activité / audit | `audit_events`, `activity_events` | services Django (`record_audit`, `record_activity`) + fonctions SQL | qui, quoi, quand, d'où, statut, valeurs autorisées |
| 4 — Logs techniques & exécutions | `execution_logs`, `system_error_events`, `scheduler_execution_runs`, `ai_execution_logs`, `connector_sync_runs`… | `track_execution`, `TracedTask`, gestionnaire d'erreurs | durée, statut, tentatives, erreurs, coûts, ids Celery |

## Séquence d'une modification

1. Requête authentifiée → contexte (utilisateur, tenant, `request_id`, `correlation_id`).
2. Transaction ouverte (`ATOMIC_REQUESTS`) ; `app.set_context()`.
3. Service Django : lecture de l'état précédent, contrôle de version optimiste, écriture.
4. Trigger `BEFORE UPDATE` : `updated_at`, `updated_by`, `version_number + 1` (aucune version pour une mise à jour sans changement).
5. Trigger `AFTER` : ligne `entity_history` (même transaction).
6. `record_audit` + `record_activity` (même transaction).
7. Commit : tout est persisté ensemble — ou rien.
8. Échec : rollback des données métier, mais l'exécution échouée et l'erreur sont écrites sur une connexion séparée (`logs`) et restent tracées.

L'auteur n'est jamais déduit d'un trigger seul : il vient du contexte poussé par Django, vérifié par JWT.

## Corrélation

`request_id` (une requête), `correlation_id` (un processus métier, propagé du frontend `X-Correlation-ID` aux tâches Celery), `execution_id`, `workflow_execution_id`, `webhook_event_id`. `GET /api/v1/history/trace/<correlation_id>` reconstitue la chaîne : audit → versions → exécutions → activité.

## Garanties testées
Voir `database/tests/10_security_traceability.sql` et `backend/tests/integration/` : versioning INSERT/UPDATE/SOFT_DELETE/RESTORE, auteur et motif, corrélation, secrets exclus, immutabilité, isolation A/B des historiques, lecture après « redémarrage » (nouvelle connexion).
