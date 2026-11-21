-- Claude as the default AI (changeable by the PILOTE). Additive and idempotent.
-- Prices are NOT assumed: the PILOTE enters them (costs stay "not computed" until then). The API key is provided by the
-- PILOTE (encrypted in ai_provider_configurations) or by the ANTHROPIC_API_KEY environment variable.
INSERT INTO public.ai_providers (code, name, api_style) VALUES ('anthropic', 'Anthropic (Claude)', 'anthropic') ON CONFLICT DO NOTHING;
UPDATE public.ai_providers SET api_style = 'anthropic', is_enabled = true WHERE code = 'anthropic';
INSERT INTO public.ai_models (provider_id, code, name, context_window)
SELECT p.id, v.code, v.name, v.ctx FROM public.ai_providers p, (VALUES
  ('claude-sonnet-5-5', 'Claude Sonnet 5.5 (par défaut)', 200000),
  ('claude-haiku-5-5', 'Claude Haiku 5.5 (économique)', 200000),
  ('claude-opus-5-5', 'Claude Opus 5.5 (premium)', 200000)) v(code, name, ctx)
WHERE p.code = 'anthropic'
ON CONFLICT (code) DO NOTHING;
-- Default route for every feature, only when the platform has no default yet (never overrides a PILOTE choice)
INSERT INTO public.ai_feature_routes (tenant_id, feature_code, model_id, priority, quality, is_enabled)
SELECT NULL, '*', m.id, 1, 'standard', true FROM public.ai_models m
 WHERE m.code = 'claude-sonnet-5-5'
   AND NOT EXISTS (SELECT 1 FROM public.ai_feature_routes r WHERE r.tenant_id IS NULL AND r.feature_code = '*');
