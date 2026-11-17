# Stratégie d'index

Générée automatiquement par `generate.py` (≈ 1 700 index) :

| Index | Règle |
|---|---|
| `(tenant_id, created_at DESC)` | toute table tenant — listes paginées et filtrage temporel |
| `(tenant_id, <fk>)` | chaque clé étrangère composite (sert aussi la FK) |
| `(<fk>)` | FK simples, colonnes utilisateur |
| `(tenant_id, status)` | toute table avec `status` |
| `(correlation_id) WHERE correlation_id IS NOT NULL` | traçabilité de bout en bout |
| `(execution_id) WHERE execution_id IS NOT NULL` | exécutions |
| `(entity_type, entity_id)`, `(request_id)`, `(actor_user_id, created_at)` | journaux d'audit/activité |
| uniques partiels `WHERE deleted_at IS NULL` | unicité compatible suppression logique |
| `NULLS NOT DISTINCT` | unicité incluant un `tenant_id` nullable (lignes partagées) |
| HNSW cosine sur `thor_memory.embedding` | recherche vectorielle (pgvector) |

## Volumétrie

- `audit_events`, `activity_events`, `execution_logs`, `application_logs` : **partitionnement mensuel** par `created_at` (+ partition par défaut), création anticipée de 3 mois par `maintenance.ensure_partitions`.
- La purge de rétention supprime par plage de dates ; à terme, un détachement de partition remplacera le `DELETE` pour les très gros volumes.
- Les écritures d'historique se font dans la même transaction (trigger) avec un coût d'une insertion ; les lectures ne sont jamais journalisées aveuglément (`record_access_logs` réservé aux exports et accès sensibles).
