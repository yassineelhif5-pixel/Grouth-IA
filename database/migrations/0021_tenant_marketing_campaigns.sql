-- Tenant Marketing Center: approved strategy -> campaign and editorial backlog.
-- No publication is scheduled here. Items remain planned until the owner explicitly activates a campaign.

CREATE TABLE IF NOT EXISTS public.tenant_marketing_campaigns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  strategy_id uuid NOT NULL,
  name text NOT NULL,
  status text NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','active','paused','completed','archived')),
  timezone text NOT NULL DEFAULT 'Europe/Paris',
  generation_time time NOT NULL DEFAULT '00:00',
  publish_requires_approval boolean NOT NULL DEFAULT true,
  starts_on date,
  ends_on date,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  updated_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  deleted_at timestamptz,
  version_number integer NOT NULL DEFAULT 1,
  correlation_id uuid,
  CONSTRAINT tenant_marketing_campaigns_tenant_id_id_key UNIQUE (tenant_id,id)
);
CREATE TABLE IF NOT EXISTS public.tenant_marketing_editorial_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
  campaign_id uuid NOT NULL,
  title text NOT NULL,
  angle text,
  primary_keyword text NOT NULL,
  secondary_keywords jsonb NOT NULL DEFAULT '[]'::jsonb,
  search_intent text,
  faq jsonb NOT NULL DEFAULT '[]'::jsonb,
  dedupe_hash text NOT NULL,
  status text NOT NULL DEFAULT 'planned'
    CHECK (status IN ('planned','queued','draft','review','approved','published','skipped','failed')),
  planned_for date,
  generated_content_id uuid,
  published_url text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  updated_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  deleted_at timestamptz,
  version_number integer NOT NULL DEFAULT 1,
  correlation_id uuid,
  CONSTRAINT tenant_marketing_editorial_items_tenant_id_id_key UNIQUE (tenant_id,id)
);
DO $$ BEGIN
  ALTER TABLE public.tenant_marketing_campaigns
    ADD CONSTRAINT tenant_marketing_campaigns_strategy_fk
    FOREIGN KEY (tenant_id,strategy_id) REFERENCES public.tenant_marketing_strategies(tenant_id,id) ON DELETE RESTRICT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE public.tenant_marketing_editorial_items
    ADD CONSTRAINT tenant_marketing_editorial_items_campaign_fk
    FOREIGN KEY (tenant_id,campaign_id) REFERENCES public.tenant_marketing_campaigns(tenant_id,id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  ALTER TABLE public.tenant_marketing_editorial_items
    ADD CONSTRAINT tenant_marketing_editorial_items_content_fk
    FOREIGN KEY (tenant_id,generated_content_id) REFERENCES public.generated_contents(tenant_id,id) ON DELETE SET NULL (generated_content_id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE UNIQUE INDEX IF NOT EXISTS tenant_marketing_editorial_dedupe
  ON public.tenant_marketing_editorial_items(tenant_id,dedupe_hash) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_tenant_marketing_campaigns_status
  ON public.tenant_marketing_campaigns(tenant_id,status,created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_tenant_marketing_editorial_due
  ON public.tenant_marketing_editorial_items(tenant_id,status,planned_for) WHERE deleted_at IS NULL;

DO $$ BEGIN
  CREATE TRIGGER trg_00_context BEFORE INSERT ON public.tenant_marketing_campaigns
    FOR EACH ROW EXECUTE FUNCTION app.tg_fill_context('versioned');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TRIGGER trg_01_touch BEFORE UPDATE ON public.tenant_marketing_campaigns
    FOR EACH ROW EXECUTE FUNCTION app.tg_touch();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TRIGGER trg_90_history AFTER INSERT OR UPDATE OR DELETE ON public.tenant_marketing_campaigns
    FOR EACH ROW EXECUTE FUNCTION app.tg_entity_history();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TRIGGER trg_00_context BEFORE INSERT ON public.tenant_marketing_editorial_items
    FOR EACH ROW EXECUTE FUNCTION app.tg_fill_context('versioned');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TRIGGER trg_01_touch BEFORE UPDATE ON public.tenant_marketing_editorial_items
    FOR EACH ROW EXECUTE FUNCTION app.tg_touch();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE TRIGGER trg_90_history AFTER INSERT OR UPDATE OR DELETE ON public.tenant_marketing_editorial_items
    FOR EACH ROW EXECUTE FUNCTION app.tg_entity_history();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['tenant_marketing_campaigns','tenant_marketing_editorial_items'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon',t);
    EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM authenticated',t);
    EXECUTE format('GRANT SELECT ON public.%I TO authenticated',t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO app_backend',t);
    EXECUTE format('DROP POLICY IF EXISTS p_auth_read ON public.%I',t);
    EXECUTE format('DROP POLICY IF EXISTS p_backend_read ON public.%I',t);
    EXECUTE format('DROP POLICY IF EXISTS p_backend_write ON public.%I',t);
    EXECUTE format('CREATE POLICY p_auth_read ON public.%I FOR SELECT TO authenticated USING (app.is_tenant_member(tenant_id) OR app.is_platform_admin())',t);
    EXECUTE format('CREATE POLICY p_backend_read ON public.%I FOR SELECT TO app_backend USING (tenant_id = app.current_tenant_id() OR app.current_is_platform() OR app.backend_user_is_member(tenant_id))',t);
    EXECUTE format('CREATE POLICY p_backend_write ON public.%I FOR ALL TO app_backend USING (tenant_id = app.current_tenant_id() OR app.current_is_platform()) WITH CHECK (tenant_id = app.current_tenant_id() OR app.current_is_platform())',t);
  END LOOP;
END $$;

COMMENT ON TABLE public.tenant_marketing_campaigns IS 'Editorial campaigns generated from an approved tenant marketing strategy. Creation does not activate publication.';
COMMENT ON TABLE public.tenant_marketing_editorial_items IS 'Planned article backlog with tenant-wide deduplication hash; publication requires later approval.';
