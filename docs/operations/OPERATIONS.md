# Exploitation

## Tâches planifiées (Celery Beat)
| Tâche | Fréquence | Rôle |
|---|---|---|
| `system_health.run_all_checks` | 5 min | tests réels, persistés |
| `system_health.beat_heartbeat` | 1 min | preuve de vie de Beat |
| `notifications.dispatch_scheduled` | 1 min | notifications planifiées |
| `licensing.expire_trials` | 10 min | expiration DEMO 72 h |
| `maintenance.ensure_partitions` | 1 j | partitions des 3 prochains mois |
| `maintenance.purge_retention` | 1 j | purge selon politiques explicites |
| `integrations.check_connectors` | 1 h | santé des comptes connectés |

Files : `default`, `health`, `notifications`, `maintenance`, `integrations` (+ `dead_letter`). Retry exponentiel avec jitter (5 tentatives) ; échec final → `system_error_events` (`dead_letter:*`). Chaque exécution → `execution_logs`.

## Diagnostiquer
1. Récupérer le `X-Request-ID` / `X-Correlation-ID` (renvoyés par l'API, affichés dans les messages d'erreur de l'UI).
2. PILOTE → Journaux → filtre Correlation ID → « Tracer la chaîne complète ».
3. PILOTE → Erreurs pour les exceptions serveur et dead letters.

## Corriger un journal (exceptionnel)
```sql
SELECT app.set_context('<pilote>', NULL, gen_random_uuid(), NULL, 'pilot', true, NULL);
SELECT app.correct_log_entry('audit_events', '<id>', '{"description":"…"}', '<motif>');
```
Tracé dans `audit_log_corrections` et `audit_events`.

## Sauvegardes
Sauvegardes et PITR Supabase (plan payant). Les exports d'audit à long terme vont dans le bucket privé `exports`.

## Runbook hebdomadaire
- Advisors Supabase sécurité & performance.
- Croissance des partitions et de `entity_history`.
- Revue des actions PILOTE (`actor_type = pilot`).
