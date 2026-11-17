# Historique et versioning

- 143 tables métier/configuration (`biz`, `conf`, `gbiz`) portent `version_number` et un trigger d'historique.
- `entity_history` : unicité `(entity_type, entity_id, version_number)` ; opérations `INSERT`, `UPDATE`, `SOFT_DELETE`, `RESTORE`, `DELETE`.
- Chaque version contient : numéro, date, auteur (`changed_by`), type d'acteur, motif (`change_reason`), ancienne valeur (`previous_data`), nouvelle valeur (`current_data`), champs modifiés, `correlation_id`.

## Concurrence
Les API d'écriture acceptent `version_number` : si la version a changé entre-temps → `409 version_conflict`.

## Consultation, comparaison, restauration
- `GET /api/v1/history/entities/<table>/<id>/versions`
- `GET /api/v1/history/entities/<table>/<id>/compare?from=1&to=3` (permission `history.read_values`)
- `POST /api/v1/history/entities/<table>/<id>/restore {version, reason}` : **la restauration crée une nouvelle version** ; l'historique n'est jamais réécrit.

## Suppression
Suppression logique (`deleted_at`, motif obligatoire) → version `SOFT_DELETE`, restaurable. Les suppressions physiques passent par `data_deletion_requests` (RGPD) avec validation.
