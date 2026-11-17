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
| `scheduler.dispatch` | 1 min | lance les programmations dues (verrou, pas de chevauchement) |
| `scheduler.recover` | 5 min | runs bloqués > 2 h → `failed` + relance ; reprise des workflows |
| `email.sync_all` | 5 min | synchronisation de secours des boîtes (Gmail, Graph, IMAP) |
| `prospects.process_campaigns` | 5 min | envoi des étapes de séquence dues (consentement et suppression revérifiés) |

Files : `default`, `health`, `notifications`, `maintenance`, `integrations` (connecteurs et e-mail) (+ `dead_letter`). Retry exponentiel avec jitter (5 tentatives) ; échec final → `system_error_events` (`dead_letter:*`). Chaque exécution → `execution_logs`.

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

## Approbations (modes de croissance)
PILOTE → *Modes de croissance* : capacités plateforme par action (`platform_action_capabilities`) ; le tenant règle ses politiques (`tenant_growth_policies`). Mode effectif = le plus restrictif des deux. Les demandes en attente (`approval_requests`) sont listées dans *Approbations* ; une décision exécute le traitement enregistré et est historisée.

## Connecteurs en échec
1. *Connecteurs* → compte → « Tester » : le message d'erreur réel du fournisseur est affiché et stocké (`connector_health_checks`, `connector_error_logs`).
2. Jeton OAuth expiré → « Reconnecter ». Clé révoquée → ressaisir les identifiants (chiffrés).
3. Webhook refusé : vérifier le secret saisi et l'horloge (fenêtre de fraîcheur 5 min).

## Rotation de la clé de chiffrement
Ajouter la nouvelle clé en tête de `SECRETS_ENCRYPTION_KEY` (liste séparée par des virgules, `MultiFernet`), redéployer, ré-enregistrer ou rechiffrer les identifiants, puis retirer l'ancienne clé.

## Sauvegardes
Sauvegardes et PITR Supabase (plan payant). Les exports d'audit à long terme vont dans le bucket privé `exports`.

## Runbook hebdomadaire
- Advisors Supabase sécurité & performance.
- Croissance des partitions et de `entity_history`.
- Revue des actions PILOTE (`actor_type = pilot`).
- Approbations en attente, connecteurs `failed`, programmations en échec répété, budget IA consommé.
