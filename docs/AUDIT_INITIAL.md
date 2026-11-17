# Rapport d'audit initial — 16/11/2026

## Dépôt GitHub `yassineelhif5-pixel/Grouth-IA`
- Dépôt **vide** : aucun commit, aucune branche, aucun fichier. Rien à préserver ni à migrer.
- Décision : création du socle complet sur `main`.

## Projet Supabase
- Le Project Ref indiqué dans le cahier des charges (`kGnxywILOqBB3GxI`) n'existe pas (format invalide). Le seul projet du compte est **« Grouth AI » — ref `nhjhmctxbrcwnkuojwzt`**, région eu-west-1, PostgreSQL 17, statut ACTIVE_HEALTHY, créé le 16/11/2026.
- Schéma `public` : 0 table, 0 fonction, 0 trigger, 0 politique, 0 migration.
- Schémas Supabase standard présents (`auth`, `storage`, `realtime`, `vault`), sans donnée utilisateur (0 utilisateur, 0 bucket).
- Extensions installées : `pgcrypto`, `uuid-ossp`, `pg_stat_statements`, `supabase_vault`. Disponibles : `vector`, `pg_trgm`, `pg_cron`, `pgtap`, `http`…
- Variables d'environnement : aucune configuration applicative existante.

## Environnement de travail
- Installation de paquets pip/npm impossible dans la session (réseau restreint) : Django et React n'ont pas pu être exécutés localement ; PostgreSQL local disponible pour tester réellement le SQL.

## Conclusion
Base et dépôt vierges : aucune contrainte de compatibilité, aucune donnée à protéger. Toutes les évolutions ont néanmoins été écrites de manière non destructive et idempotente.
