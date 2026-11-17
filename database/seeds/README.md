# database/seeds

Les objets SQL de cette catégorie sont versionnés dans `database/migrations/` (source appliquée) :

| Catégorie | Fichier(s) |
|---|---|
| policies | `0005_rls.sql` (généré), `0008_storage.sql` |
| functions | `0001_foundation.sql` (contexte), `0003_functions.sql`, `0007_provisioning.sql`, `0010_notification_read_state.sql` |
| triggers | `0004_triggers.sql` (généré) |
| seeds | `0006_partitions_and_seeds.sql` (données de référence plateforme uniquement) |

Un seul pipeline de migration : voir `docs/database/MIGRATIONS.md`.
