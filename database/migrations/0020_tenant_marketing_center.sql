-- Tenant Marketing Center: conversational marketing profile, conversations and strategy proposals.
-- Additive and idempotent. Website URLs are stored as optional context only; no crawler is triggered.

CREATE TABLE IF NOT EXISTS public.tenant_marketing_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  company_name text,
  industry text,
  offer text,
  target_audience text,
  differentiators text,
  objectives jsonb NOT NULL DEFAULT '[]'::jsonb,
  preferred_language text NOT NULL DEFAULT 'fr',
  website_url text,
  timezone text NOT NULL DEFAULT 'Europe/Paris',
  publishing_policy text NOT NULL DEFAULT 'manual_approval'
    CHECK (publishing_policy IN ('manual_approval','autonomous')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  updated_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  deleted_at timestamptz,
  version_number integer NOT NULL DEFAULT 1,
  correlation_id uuid,
  CONSTRAINT tenant_marketing_profiles_tenant_id_id_key UNIQUE (tenant_id,id)
);
CREATE UNIQUE INDEX IF NOT EXISTS tenant_marketing_profiles_tenant_key
  ON public.tenant_marketing_profiles(tenant_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS public.tenant_marketing_conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  title text NOT NULL DEFAULT 'Nouvelle stratégie marketing',
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  updated_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  deleted_at timestamptz,
  version_number integer NOT NULL DEFAULT 1,
  correlation_id uuid,
  CONSTRAINT tenant_marketing_conversations_tenant_id_id_key UNIQUE (tenant_id,id)
);

CREATE TABLE IF NOT EXISTS public.tenant_marketing_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  conversation_id uuid NOT NULL,
  role text NOT NULL CHECK (role IN ('user','assistant','system')),
  content text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  provider_code text,
  model_code text,
  input_tokens integer,
  output_tokens integer,
  cost_cents numeric(18,6),
  created_at timestamptz NOT NULL DEFAULT now(),
  correlation_id uuid,
  CONSTRAINT tenant_marketing_messages_tenant_id_id_key UNIQUE (tenant_id,id)
);

CREATE TABLE IF NOT EXISTS public.tenant_marketing_strategies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  conversation_id uuid NOT NULL,
  title text NOT NULL DEFAULT 'Proposition de stratégie marketing',
  summary text NOT NULL DEFAULT '',
  strategy jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('draft','proposed','approved','active','rejected','archived')),
  approved_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  approved_at timestamptz,
  activated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  updated_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  deleted_at timestamptz,
  version_number integer NOT NULL DEFAULT 1,
  correlation_id uuid,
  CONSTRAINT tenant_marketing_strategies_tenant_id_id_key UNIQUE (tenant_id,id)
);

DO $$ BEGIN
  ALTER TABLE public.tenant_marketing_conversations
    ADD CONSTRAINT tenant_marketing_conversations_user_tenant_fk
    FOREIGN KEY (tenant_id,user_id) REFERENCES public.tenant_members(tenant_id,user_id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE public.tenant_marketing_messages
    ADD CONSTRAINT tenant_marketing_messages_conversation_fk
    FOREIGN KEY (tenant_id,conversation_id)
    REFERENCES public.tenant_marketing_conversations(tenant_id,id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE public.tenant_marketing_strategies
    ADD CONSTRAINT tenant_marketing_strategies_conversation_fk
    FOREIGN KEY (tenant_id,conversation_id)
    REFERENCES public.tenant_marketing_conversations(tenant_id,id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS ix_tenant_marketing_conversations_user
  ON public.tenant_marketing_conversations(tenant_id,user_id,updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_tenant_marketing_messages_conversation
  ON public.tenant_marketing_messages(tenant_id,conversation_id,created_at);
CREATE INDEX IF NOT EXISTS ix_tenant_marketing_strategies_status
  ON public.tenant_marketing_strategies(tenant_id,status,created_at DESC) WHERE deleted_at IS NULL;

-- Tenant-aware context, version history and touch triggers.
DO $$ BEGIN
  CREATE TRIGGER trg_00_context BEFORE INSERT ON public.tenant_marketing_profiles
    FOR EACH ROW EXECUTE FUNCTION app.tg_fill_context('versioned');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TRIGGER trg_01_touch BEFORE UPDATE ON public.tenant_marketing_profiles
    FOR EACH ROW EXECUTE FUNCTION app.tg_touch();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TRIGGER trg_90_history AFTER INSERT OR UPDATE OR DELETE ON public.tenant_marketing_profiles
    FOR EACH ROW EXECUTE FUNCTION app.tg_entity_history();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TRIGGER trg_00_context BEFORE INSERT ON public.tenant_marketing_conversations
    FOR EACH ROW EXECUTE FUNCTION app.tg_fill_context('versioned');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TRIGGER trg_01_touch BEFORE UPDATE ON public.tenant_marketing_conversations
    FOR EACH ROW EXECUTE FUNCTION app.tg_touch();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TRIGGER trg_90_history AFTER INSERT OR UPDATE OR DELETE ON public.tenant_marketing_conversations
    FOR EACH ROW EXECUTE FUNCTION app.tg_entity_history();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TRIGGER trg_00_context BEFORE INSERT ON public.tenant_marketing_messages
    FOR EACH ROW EXECUTE FUNCTION app.tg_fill_context();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TRIGGER trg_01_append_only BEFORE UPDATE OR DELETE ON public.tenant_marketing_messages
    FOR EACH ROW EXECUTE FUNCTION app.tg_append_only();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TRIGGER trg_00_context BEFORE INSERT ON public.tenant_marketing_strategies
    FOR EACH ROW EXECUTE FUNCTION app.tg_fill_context('versioned');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TRIGGER trg_01_touch BEFORE UPDATE ON public.tenant_marketing_strategies
    FOR EACH ROW EXECUTE FUNCTION app.tg_touch();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TRIGGER trg_90_history AFTER INSERT OR UPDATE OR DELETE ON public.tenant_marketing_strategies
    FOR EACH ROW EXECUTE FUNCTION app.tg_entity_history();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Row-level security: tenant members may read; backend writes require the verified tenant context.
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['tenant_marketing_profiles','tenant_marketing_conversations','tenant_marketing_messages','tenant_marketing_strategies'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon',t);
    EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM authenticated',t);
    EXECUTE format('GRANT SELECT ON public.%I TO authenticated',t);
    EXECUTE format('DROP POLICY IF EXISTS p_auth_read ON public.%I',t);
    EXECUTE format('DROP POLICY IF EXISTS p_backend_read ON public.%I',t);
    EXECUTE format('DROP POLICY IF EXISTS p_backend_write ON public.%I',t);
    EXECUTE format('CREATE POLICY p_auth_read ON public.%I FOR SELECT TO authenticated USING (app.is_tenant_member(tenant_id) OR app.is_platform_admin())',t);
    EXECUTE format('CREATE POLICY p_backend_read ON public.%I FOR SELECT TO app_backend USING (tenant_id = app.current_tenant_id() OR app.current_is_platform() OR app.backend_user_is_member(tenant_id))',t);
    IF t = 'tenant_marketing_messages' THEN
      EXECUTE format('GRANT SELECT, INSERT ON public.%I TO app_backend',t);
      EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON public.%I FROM app_backend',t);
      EXECUTE format('CREATE POLICY p_backend_write ON public.%I FOR INSERT TO app_backend WITH CHECK (tenant_id = app.current_tenant_id() OR app.current_is_platform())',t);
    ELSE
      EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO app_backend',t);
      EXECUTE format('CREATE POLICY p_backend_write ON public.%I FOR ALL TO app_backend USING (tenant_id = app.current_tenant_id() OR app.current_is_platform()) WITH CHECK (tenant_id = app.current_tenant_id() OR app.current_is_platform())',t);
    END IF;
  END LOOP;
END $$;

COMMENT ON TABLE public.tenant_marketing_profiles IS 'Tenant marketing context collected through owner conversation; website_url is optional and is not crawled.';
COMMENT ON TABLE public.tenant_marketing_conversations IS 'Tenant-isolated conversations for the Marketing Center assistant.';
COMMENT ON TABLE public.tenant_marketing_messages IS 'Append-only tenant marketing assistant conversation messages.';
COMMENT ON TABLE public.tenant_marketing_strategies IS 'AI-proposed marketing strategies requiring explicit owner approval before activation.';
