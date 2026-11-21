-- Allow the 'site_files' scheduler category (forced site corrections pushed via the connector service). Idempotent.
ALTER TABLE public.tenant_schedulers DROP CONSTRAINT IF EXISTS tenant_schedulers_category_check;
ALTER TABLE public.tenant_schedulers ADD CONSTRAINT tenant_schedulers_category_check
  CHECK (category IN ('seo','geo','articles','pages','social','videos','opportunities','social_monitoring','prospects','crm','reporting','intelligence','agents','site_files'));
