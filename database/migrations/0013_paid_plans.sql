-- Growth IA - offres payantes TTC mensuelles : Starter 20 EUR, Pro 50 EUR, Professionnelle 200 EUR (appliquee le 18/11/2026).
-- Modules et quotas copies de STARTER / GROWTH / GROWTH_ENTREPRISE. Idempotent.
ALTER TABLE public.subscription_plans DROP CONSTRAINT IF EXISTS subscription_plans_code_check;
ALTER TABLE public.subscription_plans ADD CONSTRAINT subscription_plans_code_check CHECK (code = ANY (ARRAY['DEMO','STARTER','GROWTH','GROWTH_ENTREPRISE','OFFRE_STARTER','OFFRE_PRO','OFFRE_PROFESSIONNELLE']));

INSERT INTO public.subscription_plans (code, name, description, is_trial, trial_duration_hours, price_monthly_cents, currency, is_active, sort_order)
VALUES
  ('OFFRE_STARTER', 'Starter', 'Offre Starter - 20 EUR TTC / mois', false, NULL, 2000, 'EUR', true, 40),
  ('OFFRE_PRO', 'Pro', 'Offre Pro - 50 EUR TTC / mois', false, NULL, 5000, 'EUR', true, 50),
  ('OFFRE_PROFESSIONNELLE', 'Professionnelle', 'Offre Professionnelle - 200 EUR TTC / mois', false, NULL, 20000, 'EUR', true, 60)
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description,
  price_monthly_cents = EXCLUDED.price_monthly_cents, is_active = true, sort_order = EXCLUDED.sort_order, updated_at = now();

WITH map(new_code, src_code) AS (VALUES ('OFFRE_STARTER', 'STARTER'), ('OFFRE_PRO', 'GROWTH'), ('OFFRE_PROFESSIONNELLE', 'GROWTH_ENTREPRISE'))
INSERT INTO public.subscription_plan_features (plan_id, feature_id, enabled)
SELECT n.id, f.feature_id, f.enabled
  FROM map JOIN public.subscription_plans n ON n.code = map.new_code
           JOIN public.subscription_plans s ON s.code = map.src_code
           JOIN public.subscription_plan_features f ON f.plan_id = s.id
 WHERE NOT EXISTS (SELECT 1 FROM public.subscription_plan_features x WHERE x.plan_id = n.id AND x.feature_id = f.feature_id);

WITH map(new_code, src_code) AS (VALUES ('OFFRE_STARTER', 'STARTER'), ('OFFRE_PRO', 'GROWTH'), ('OFFRE_PROFESSIONNELLE', 'GROWTH_ENTREPRISE'))
INSERT INTO public.subscription_plan_quotas (plan_id, quota_code, limit_value, period)
SELECT n.id, q.quota_code, q.limit_value, q.period
  FROM map JOIN public.subscription_plans n ON n.code = map.new_code
           JOIN public.subscription_plans s ON s.code = map.src_code
           JOIN public.subscription_plan_quotas q ON q.plan_id = s.id
 WHERE NOT EXISTS (SELECT 1 FROM public.subscription_plan_quotas x WHERE x.plan_id = n.id AND x.quota_code = q.quota_code);
