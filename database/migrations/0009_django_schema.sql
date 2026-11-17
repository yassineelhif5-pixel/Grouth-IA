-- Growth IA — Migration 0009 — private schema for Django/Celery-beat internal tables
-- Django connects with search_path=django,public: its own tables (django_migrations, celery beat…)
-- land here, outside the schemas exposed by the Supabase Data API.
CREATE SCHEMA IF NOT EXISTS django;
REVOKE ALL ON SCHEMA django FROM PUBLIC;
DO $$ BEGIN EXECUTE 'REVOKE ALL ON SCHEMA django FROM anon, authenticated'; EXCEPTION WHEN undefined_object THEN NULL; END $$;
GRANT USAGE ON SCHEMA django TO app_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA django TO app_backend;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA django TO app_backend;
ALTER DEFAULT PRIVILEGES IN SCHEMA django GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_backend;
ALTER DEFAULT PRIVILEGES IN SCHEMA django GRANT USAGE, SELECT ON SEQUENCES TO app_backend;
