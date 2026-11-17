# Rétention, archivage et RGPD

`data_retention_policies` : par tenant (ou plateforme si `tenant_id` null), catégorie, type d'historique, durée, mode d'archivage (`none|storage_export|cold_table`), règle (`delete|anonymize|keep`).

| Catégorie (défaut plateforme) | Durée | Règle |
|---|---|---|
| audit_events | 5 ans | keep (archivage Storage) |
| entity_history | 5 ans | keep (archivage Storage) |
| activity_events | 2 ans | delete |
| execution_logs | 1 an | delete |
| application_logs, system_health_results | 90 j | delete |
| record_access_logs | 1 an | delete |
| notifications | 180 j | delete |
| personal_data | 3 ans | anonymize |

- `app.purge_expired(table, tenant)` ne supprime **que** s'il existe une politique active `delete` ; sans politique, rien n'est supprimé. Chaque purge est auditée (`retention.purged`).
- Tâche Celery quotidienne `maintenance.purge_retention`.
- Demandes RGPD : `data_deletion_requests` (demandeur, périmètre, motif, statut, validation, exécution, résultat) ; exports : `export_jobs` (lien à durée limitée).
- Pièces jointes volumineuses : buckets privés Supabase Storage, métadonnées en PostgreSQL.
- Les données personnelles ne sont pas conservées indéfiniment au nom de l'historisation : la catégorie `personal_data` est anonymisée à échéance.
