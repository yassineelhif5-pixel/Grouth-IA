-- Growth IA — PROMPT 3: user licences + visibility programmes. Additive and idempotent.

-- ── Licence types (catalogue, editable by the PILOTE) ──
INSERT INTO public.license_types (code, name, description, modules, sort_order) VALUES
  ('FULL', 'Complète', 'Accès à tous les modules de l''offre du tenant', '["*"]', 10),
  ('MARKETING', 'Marketing & visibilité', 'SEO, GEO, contenus, réseaux sociaux, programmations, reporting',
   '["core","products","websites","history","reporting","scheduler","workflows","connectors","seo","geo","content","pages","social","video","opportunities","social_hunter","intelligence","thor"]', 20),
  ('SALES', 'Commerciale', 'Prospection, CRM, e-mail, WhatsApp, opportunités, reporting',
   '["core","products","history","reporting","scheduler","prospects","crm","email_center","whatsapp","opportunities","thor"]', 30),
  ('VIEWER', 'Lecture', 'Consultation des tableaux de bord, rapports et historiques',
   '["core","products","websites","history","reporting","seo","geo"]', 40)
ON CONFLICT (code) DO NOTHING;

-- ── Can this user use this module, given the licence assigned to them? ──
-- * tenant without any licence allocation → no licence restriction (backward compatible)
-- * tenant owner / admin → always allowed (they administer the tenant)
-- * otherwise the member's active licence must grant the module ("*" = every module of the plan)
CREATE OR REPLACE FUNCTION app.member_license_allows(p_tenant uuid, p_user uuid, p_module text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT CASE
    WHEN NOT EXISTS (SELECT 1 FROM public.tenant_license_allocations a WHERE a.tenant_id = p_tenant AND a.deleted_at IS NULL) THEN true
    WHEN app.has_tenant_role(p_tenant, p_user, ARRAY['tenant_owner','tenant_admin']) THEN true
    ELSE EXISTS (
      SELECT 1 FROM public.member_license_assignments la
        JOIN public.tenant_members m ON m.id = la.member_id
        JOIN public.license_types lt ON lt.id = la.license_type_id
       WHERE la.tenant_id = p_tenant AND m.user_id = p_user AND la.status = 'active' AND la.deleted_at IS NULL
         AND m.deleted_at IS NULL AND lt.is_active
         AND (lt.modules ? '*' OR lt.modules ? p_module))
  END
$$;
REVOKE ALL ON FUNCTION app.member_license_allows(uuid, uuid, text) FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    EXECUTE 'REVOKE ALL ON FUNCTION app.member_license_allows(uuid, uuid, text) FROM anon';
  END IF;
END $$;
GRANT EXECUTE ON FUNCTION app.member_license_allows(uuid, uuid, text) TO app_backend;

-- ── Default quota for visibility audits (editable by the PILOTE, per plan or per tenant) ──
INSERT INTO public.subscription_plan_quotas (plan_id, quota_code, limit_value, period)
SELECT p.id, 'visibility.audits.monthly',
       CASE p.code WHEN 'DEMO' THEN 2 WHEN 'STARTER' THEN 5 WHEN 'OFFRE_STARTER' THEN 5 WHEN 'GROWTH' THEN 20 WHEN 'OFFRE_PRO' THEN 20 ELSE NULL END,
       'month'
  FROM public.subscription_plans p
ON CONFLICT (plan_id, quota_code) DO NOTHING;

-- existing tenants receive the new quota from their current plan (new tenants get it through change_plan)
INSERT INTO public.tenant_license_quotas (tenant_id, quota_code, limit_value, period, period_start, source)
SELECT s.tenant_id, q.quota_code, q.limit_value, q.period, now(), 'plan'
  FROM public.tenant_subscriptions s
  JOIN public.subscription_plan_quotas q ON q.plan_id = s.plan_id AND q.quota_code = 'visibility.audits.monthly'
 WHERE s.deleted_at IS NULL
   AND NOT EXISTS (SELECT 1 FROM public.tenant_license_quotas x WHERE x.tenant_id = s.tenant_id
                     AND x.quota_code = 'visibility.audits.monthly' AND x.deleted_at IS NULL);
