-- Tenant Marketing Center: scheduler configuration and safe draft generation tracking.
-- The scheduler only creates Growth AI drafts. It never approves or publishes content.

ALTER TABLE public.tenant_marketing_campaigns
  ADD COLUMN IF NOT EXISTS content_project_id uuid,
  ADD COLUMN IF NOT EXISTS generation_enabled boolean NOT NULL DEFAULT false;

DO $$ BEGIN
  ALTER TABLE public.tenant_marketing_campaigns
    ADD CONSTRAINT tenant_marketing_campaigns_project_fk
    FOREIGN KEY (tenant_id,content_project_id) REFERENCES public.content_projects(tenant_id,id) ON DELETE RESTRICT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE public.tenant_marketing_editorial_items
  ADD COLUMN IF NOT EXISTS generation_attempts integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS generation_error text,
  ADD COLUMN IF NOT EXISTS generated_at timestamptz;

CREATE INDEX IF NOT EXISTS ix_marketing_due_items
  ON public.tenant_marketing_editorial_items(status,planned_for,updated_at)
  WHERE deleted_at IS NULL AND status IN ('planned','queued');

COMMENT ON COLUMN public.tenant_marketing_campaigns.generation_enabled IS
  'Explicit tenant opt-in for scheduled draft generation. This does not enable publishing.';
COMMENT ON COLUMN public.tenant_marketing_campaigns.content_project_id IS
  'Tenant-owned Content Studio project used as the destination for generated drafts.';
COMMENT ON COLUMN public.tenant_marketing_editorial_items.generation_attempts IS
  'Number of scheduler dispatch attempts; stale queued items can be recovered safely.';

DO $$ BEGIN
  ALTER TABLE public.tenant_marketing_editorial_items
    DROP CONSTRAINT IF EXISTS tenant_marketing_editorial_items_status_check;
  ALTER TABLE public.tenant_marketing_editorial_items
    ADD CONSTRAINT tenant_marketing_editorial_items_status_check
    CHECK (status IN ('planned','queued','generating','draft','review','approved','published','skipped','failed'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
