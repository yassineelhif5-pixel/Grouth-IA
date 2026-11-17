# Monitoring

- **System Health** (console PILOTE) : tests réels persistés dans `system_health_results`, exécutés toutes les 5 min par Celery Beat.
- **Logs structurés JSON** (stdout) avec `request_id`, `correlation_id`, `tenant_id` — à collecter par la plateforme d'hébergement (Loki, Datadog, CloudWatch…).
- **Erreurs serveur et dead letters** : `system_error_events` (consultables dans PILOTE → Erreurs).
- **Supabase** : advisors sécurité/performance (`get_advisors`) à intégrer au runbook hebdomadaire.
- Endpoints de sonde : `GET /api/v1/health/live`, `GET /api/v1/health/ready`.
