# Politiques RLS

RLS est activée sur **100 %** des tables `public` (vérifié par test SQL et par le check System Health `db.rls`), y compris les partitions (verrouillées : accès uniquement via la table parente).

## Rôles

| Rôle | Usage | Droits |
|---|---|---|
| `anon` | visiteur non connecté | aucun |
| `authenticated` | navigateur (JWT Supabase) | `SELECT` uniquement, filtré par les politiques `p_auth_read` |
| `app_backend` | Django / Celery (`SET ROLE`) | lecture/écriture filtrées par `p_backend_read` / `p_backend_write` ; `SELECT, INSERT` seulement sur les journaux |
| `service_role` | opérations d'administration Supabase | BYPASSRLS (jamais exposé au navigateur) |

## Profils de lecture (`p_auth_read`)

| Profil | Expression | Exemples |
|---|---|---|
| member | `app.is_tenant_member(tenant_id)` | produits, sites, scheduler |
| admin | `app.is_tenant_admin(tenant_id)` | audit, historique, abonnements, invitations |
| self | `user_id = auth.uid()` | profil, préférences, notifications |
| global | `true` | plans, modules, catalogue connecteurs |
| pilot | réservé PILOTE | System Health, configurations globales |
| none | aucune politique (backend seul) | jetons d'invitation, credentials, idempotence |
| member_or_shared | tenant ou ligne partagée (`tenant_id IS NULL`) | rôles système, templates de prompts |

`OR app.is_platform_admin()` est ajouté pour les données de gouvernance, **pas** pour les modules métier privés (`products`, `websites`, `seo`, `geo`, `content`, `social`, `opportunities`, `prospects`, `email_center`, `intelligence`, `thor`).

## Backend (`app_backend`)

- Lecture : `tenant_id = app.current_tenant_id() OR app.current_is_platform() OR app.backend_user_is_member(tenant_id)`.
- Écriture : `tenant_id = app.current_tenant_id() OR app.current_is_platform()`.
- `app.current_is_platform()` n'est vrai que pour les rôles backend : un JWT utilisateur ne peut jamais l'activer.

## Fonctions de sécurité

`app.is_platform_admin`, `app.is_member_of`, `app.is_tenant_member`, `app.is_tenant_admin`, `app.has_tenant_role`, `app.has_permission` — toutes `SECURITY DEFINER`, `search_path = ''`, `STABLE`.

## Storage

Buckets privés `tenant-files`, `email-attachments`, `reports`, `exports`. Convention de chemin `<tenant_id>/<module>/…` ; lecture autorisée aux membres du tenant (exports : admins). Écritures via Django uniquement.

## Tests

`database/tests/10_security_traceability.sql` (45 assertions) — exécuté en local, en CI et sur le projet Supabase.
