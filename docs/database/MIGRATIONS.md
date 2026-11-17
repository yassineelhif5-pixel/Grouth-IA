# Migrations

| Fichier | Contenu | Généré |
|---|---|---|
| `0001_foundation.sql` | schémas `app`/`extensions`, extensions, rôle `app_backend`, fonctions de contexte | non |
| `0002_tables.sql` | 276 tables, contraintes, FK (composites tenant), index, commentaires, colonnes pgvector | oui |
| `0003_functions.sql` | helpers de sécurité, triggers de traçabilité, correction contrôlée, purge de rétention, partitions | non |
| `0004_triggers.sql` | attache des triggers (contexte, touch/version, historique, append-only) | oui |
| `0005_rls.sql` | RLS, grants, politiques | oui |
| `0006_partitions_and_seeds.sql` | partitions mensuelles + données de référence plateforme | non |
| `0007_provisioning.sql` | inscription DEMO transactionnelle, expiration des essais | non |
| `0008_storage.sql` | buckets privés + politiques Storage | non |
| `0009_django_schema.sql` | schéma privé `django` pour les tables internes Django/Celery Beat | non |
| `0010_notification_read_state.sql` | marquage lu contrôlé des notifications (journal append-only) | non |

## Règles

- **Non destructif** : `CREATE … IF NOT EXISTS`, `CREATE OR REPLACE`, `ON CONFLICT DO NOTHING`, FK ajoutées dans des blocs idempotents. Jamais de `DROP TABLE`, `TRUNCATE` ni reset.
- **Idempotent** : la CI applique toutes les migrations deux fois puis lance les tests.
- **Pipeline unique** : `python manage.py migrate` (avec `DB_ROLE=` vide, rôle propriétaire) applique les fichiers via `apps/core/migrations/0001_growth_sql_schema.py`.
- **Dérive interdite** : la CI régénère le schéma et échoue si `git diff` n'est pas vide.

## Faire évoluer le schéma

1. Modifier `database/schema/spec_*.py` (nouvelle table/colonne) — ou écrire un nouveau fichier `00NN_*.sql` pour des objets non générés.
2. `python database/schema/generate.py`.
3. `PGURL=… infrastructure/scripts/db_local.sh --tests`.
4. Pour un changement non additif (renommage, type), écrire une migration SQL explicite et réversible plutôt que modifier le DSL seul.
5. Ajouter une migration Django `apps/core/migrations/000N_*.py` qui exécute le nouveau fichier.

## État du projet Supabase `nhjhmctxbrcwnkuojwzt`

Les migrations 0001 à 0010 ont été appliquées à partir des fichiers du dépôt (contrôle md5) et les tests SQL y ont été exécutés avec succès (transaction annulée).
