# Docker

Images : `backend/Dockerfile` (Django + Celery, utilisateur non-root), `frontend/Dockerfile` (build Vite → nginx).
Orchestration locale : `docker-compose.yml` à la racine (redis, migrate, backend, worker, beat, frontend).
La base, l'authentification et le stockage sont fournis par Supabase (pas de PostgreSQL local en production).
