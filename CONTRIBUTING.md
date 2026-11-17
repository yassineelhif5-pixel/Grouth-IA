# Contribuer à Growth IA

1. Branche depuis `main` (`feat/…`, `fix/…`), PR obligatoire, CI verte requise.
2. **Schéma** : modifier `database/schema/spec_*.py`, lancer `python database/schema/generate.py`, committer les fichiers générés. Jamais d'édition manuelle des fichiers `GENERATED`.
3. **Écritures métier** : passer par `apps.core.services` (`audited_create/update/soft_delete/restore`) ou une vue héritant de `AuditedTenantViewSet` — elles garantissent version, historique, audit et activité dans la même transaction.
4. **Nouvelle vue** : hériter de `GrowthAPIView`/`GrowthViewSet`, déclarer `permission_map`, `required_module` ; `platform_scoped = True` pour la console PILOTE.
5. **Tâches** : `@app.task(base=TracedTask, module="…")` et `.delay_traced()` pour propager le contexte.
6. **Jamais** : de secret dans le code ou les logs, de `tenant_id` lu depuis le client, de suppression physique de données métier, de test déclaré réussi sans exécution.
7. Tests : `pytest` (unitaires), `RUN_INTEGRATION=1 pytest` (PostgreSQL), `infrastructure/scripts/db_local.sh --tests` (SQL), `npm test` (frontend).
8. Commits : Conventional Commits.
