# Événements d'audit

Table `audit_events` (partitionnée par mois, immuable). Champs : `tenant_id` (null = opération globale), `actor_user_id`, `actor_type` (`user|pilot|system|celery|agent|webhook|anonymous`), `action`, `module`, `entity_type`, `entity_id`, `description`, `before_data`, `after_data` (expurgés), `source` (`api|admin|celery|webhook|sql|system|frontend`), `status` (`success|failure|denied`), `ip_address`, `user_agent`, `request_id`, `correlation_id`.

## Catalogue initial

| Action | Module | Déclencheur |
|---|---|---|
| `tenant.provisioned`, `subscription.trial_started` | tenants / licensing | inscription DEMO (SQL) |
| `signup.demo_completed` | accounts | API |
| `tenant.created`, `tenant.suspended`, `tenant.active`, `pilot.tenant.viewed` | tenants | console PILOTE |
| `license.plan_changed`, `license.quota_overridden`, `plan.quota_updated`, `license.request_created` | licensing | PILOTE / tenant |
| `quota.exceeded` (`denied`) | licensing | dépassement de quota |
| `subscription.trial_expired` | licensing | Celery |
| `authorization.module_enabled/disabled/suspended` | permissions | PILOTE |
| `connector.authorization_changed` | integrations | PILOTE |
| `member.role_changed`, `member.removed` | memberships | tenant admin |
| `invitation.created/revoked/accepted/accept_denied` | invitations | tenant / invité |
| `<table>.created/updated/deleted/restored` | module concerné | CRUD audité |
| `history.exported` | history | export CSV |
| `journal.corrected` | audit | correction administrative |
| `retention.purged` | audit | Celery |
| `system_health.run` | system_health | PILOTE |

## Règles
- Jamais de mot de passe, jeton ou secret dans `before_data`/`after_data` (`apps/core/redaction.py` + colonnes `secret`).
- Les valeurs avant/après ne sont renvoyées par l'API qu'avec la permission `history.read_values`.
- Toute action PILOTE est auditée avec `actor_type = pilot`, `source = admin`.
