# Lancement local sous Windows — Redis, Celery worker, Celery Beat

Copiez ces fichiers à la racine du projet (à côté de `.env`) sur le poste Windows.

1. `10-activer-redis-celery.bat` : télécharge Redis pour Windows (portage tporadowski 5.0.14.1, BSD) dans `tools\redis`,
   sauvegarde `.env` en `.env.avant-redis`, puis règle `REDIS_URL=redis://localhost:6379/0` et `CELERY_TASK_ALWAYS_EAGER=false`.
2. `3-demarrer.bat` : démarre Redis, le worker Celery (`--pool=solo`, toutes les files), Celery Beat (planificateur en base),
   l'API et le site. Journaux dans `logs\worker.log` et `logs\beat.log`.
3. `10b-desactiver-redis-celery.bat` : revient au mode sans Redis (tâches exécutées directement par l'API).

Redis n'écoute que sur 127.0.0.1, sans persistance (cache et broker uniquement : l'état métier reste dans PostgreSQL).

Autres scripts :
- `0-relancer-tout.bat` : arrête tout (`0-arreter.bat` → `_stop.ps1`, par ports 8000/5173/6379 et commandes), applique les migrations puis démarre.
- `11-configurer-cles.bat` : saisie masquée de `ANTHROPIC_API_KEY` (Claude, modèle par défaut) et `SUPABASE_SERVICE_ROLE_KEY`, écrites dans `.env`
  (sauvegarde `.env.avant-cles`, UTF-8 sans BOM), puis relance proposée.
