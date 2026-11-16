-- Growth IA — Migration 0001 — foundation: schemas, extensions, roles, request context
-- Non destructive & idempotent. Applied by the `postgres` role (Supabase) via Django migrations.

CREATE SCHEMA IF NOT EXISTS extensions;
CREATE SCHEMA IF NOT EXISTS app;
COMMENT ON SCHEMA app IS 'Growth IA internal functions (context, security helpers, traceability triggers).';

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;
DO $$ BEGIN
  CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'pgvector unavailable: embedding columns skipped';
END $$;

-- Role used by Django / Celery (SET ROLE app_backend). Subject to RLS (not BYPASSRLS).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_backend') THEN
    CREATE ROLE app_backend NOLOGIN NOINHERIT;
  END IF;
END $$;
DO $$ BEGIN
  EXECUTE format('GRANT app_backend TO %I', current_user);
EXCEPTION WHEN OTHERS THEN RAISE NOTICE 'could not grant app_backend to %: %', current_user, SQLERRM;
END $$;

GRANT USAGE ON SCHEMA public, app, extensions TO app_backend;
GRANT USAGE ON SCHEMA app TO authenticated;
GRANT USAGE ON SCHEMA auth TO app_backend;
GRANT EXECUTE ON FUNCTION auth.uid() TO app_backend;
REVOKE ALL ON SCHEMA app FROM anon;

-- ── Request context (set by Django per transaction with SET LOCAL semantics) ──
CREATE OR REPLACE FUNCTION app._guc_uuid(p_name text) RETURNS uuid
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT CASE WHEN coalesce(current_setting(p_name, true), '') ~* '^[0-9a-f-]{36}$'
              THEN current_setting(p_name, true)::uuid END
$$;

CREATE OR REPLACE FUNCTION app.current_user_id() RETURNS uuid
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT coalesce(app._guc_uuid('app.user_id'), auth.uid())
$$;

CREATE OR REPLACE FUNCTION app.current_tenant_id() RETURNS uuid
LANGUAGE sql STABLE SET search_path = '' AS $$ SELECT app._guc_uuid('app.tenant_id') $$;

CREATE OR REPLACE FUNCTION app.current_correlation_id() RETURNS uuid
LANGUAGE sql STABLE SET search_path = '' AS $$ SELECT app._guc_uuid('app.correlation_id') $$;

CREATE OR REPLACE FUNCTION app.current_request_id() RETURNS uuid
LANGUAGE sql STABLE SET search_path = '' AS $$ SELECT app._guc_uuid('app.request_id') $$;

-- Platform scope is honoured only for backend roles, never for end-user JWT roles.
CREATE OR REPLACE FUNCTION app.current_is_platform() RETURNS boolean
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT coalesce(current_setting('app.is_platform', true), '') = 'on'
     AND current_user::text IN ('app_backend', 'postgres', 'service_role')
$$;

CREATE OR REPLACE FUNCTION app.current_actor_type() RETURNS text
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT coalesce(nullif(current_setting('app.actor_type', true), ''),
                  CASE WHEN auth.uid() IS NOT NULL THEN 'user' ELSE 'system' END)
$$;

CREATE OR REPLACE FUNCTION app.change_reason() RETURNS text
LANGUAGE sql STABLE SET search_path = '' AS $$ SELECT nullif(current_setting('app.change_reason', true), '') $$;

-- Sets the whole context for the current transaction (is_local = true).
CREATE OR REPLACE FUNCTION app.set_context(
  p_user_id uuid, p_tenant_id uuid, p_correlation_id uuid,
  p_request_id uuid DEFAULT NULL, p_actor_type text DEFAULT 'user',
  p_is_platform boolean DEFAULT false, p_change_reason text DEFAULT NULL
) RETURNS void LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  PERFORM set_config('app.user_id', coalesce(p_user_id::text, ''), true);
  PERFORM set_config('app.tenant_id', coalesce(p_tenant_id::text, ''), true);
  PERFORM set_config('app.correlation_id', coalesce(p_correlation_id::text, ''), true);
  PERFORM set_config('app.request_id', coalesce(p_request_id::text, ''), true);
  PERFORM set_config('app.actor_type', coalesce(p_actor_type, 'user'), true);
  PERFORM set_config('app.is_platform', CASE WHEN p_is_platform THEN 'on' ELSE '' END, true);
  PERFORM set_config('app.change_reason', coalesce(p_change_reason, ''), true);
END $$;

REVOKE EXECUTE ON FUNCTION app.set_context(uuid, uuid, uuid, uuid, text, boolean, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION app.set_context(uuid, uuid, uuid, uuid, text, boolean, text) TO app_backend;
