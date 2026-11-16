-- Growth IA — Migration 0006 — partitions + platform reference data (idempotent; no tenant/business data)

SELECT app.ensure_monthly_partitions(t, 3)
  FROM unnest(ARRAY['audit_events', 'activity_events', 'execution_logs', 'application_logs']) t;

-- Platform roles
INSERT INTO public.platform_roles (code, name, description) VALUES
  ('PILOTE', 'Pilote', 'Administrateur global de la plateforme Growth IA (accès audité)'),
  ('SUPPORT', 'Support', 'Support plateforme en lecture, accès aux données privées sur demande auditée')
ON CONFLICT DO NOTHING;

-- System tenant roles (tenant_id NULL = shared by every tenant)
INSERT INTO public.tenant_roles (tenant_id, code, name, description, is_system) VALUES
  (NULL, 'tenant_owner', 'Propriétaire', 'Propriétaire du tenant (tous droits, facturation)', true),
  (NULL, 'tenant_admin', 'Administrateur', 'Administre membres, licences, connecteurs et paramètres', true),
  (NULL, 'tenant_member', 'Membre', 'Utilise les modules autorisés', true),
  (NULL, 'tenant_viewer', 'Lecteur', 'Consultation seule', true)
ON CONFLICT DO NOTHING;

-- Modules & features
INSERT INTO public.platform_modules (code, name, category, is_core, sort_order) VALUES
  ('core', 'Socle', 'platform', true, 0),
  ('products', 'Produits', 'platform', true, 10),
  ('websites', 'Sites web', 'platform', true, 20),
  ('connectors', 'Connecteurs', 'platform', false, 30),
  ('scheduler', 'Scheduler', 'platform', true, 40),
  ('reporting', 'Reporting', 'platform', true, 50),
  ('history', 'Centre d''historique', 'platform', true, 60),
  ('seo', 'SEO', 'growth', false, 100),
  ('geo', 'GEO', 'growth', false, 110),
  ('content', 'Content', 'growth', false, 120),
  ('social', 'Social & Vidéos', 'growth', false, 130),
  ('opportunities', 'Opportunity Hunter', 'growth', false, 140),
  ('prospects', 'Smart Prospect & CRM', 'growth', false, 150),
  ('email_center', 'Email Center', 'growth', false, 160),
  ('intelligence', 'Growth Intelligence', 'growth', false, 170),
  ('thor', 'THOR', 'growth', false, 180)
ON CONFLICT DO NOTHING;

INSERT INTO public.platform_module_features (module_id, code, name)
SELECT m.id, m.code || '.access', 'Accès ' || m.name FROM public.platform_modules m
ON CONFLICT DO NOTHING;

-- Permissions
INSERT INTO public.permissions (code, module_code, name, scope) VALUES
  ('tenant.settings.read', 'core', 'Lire les paramètres', 'tenant'),
  ('tenant.settings.manage', 'core', 'Gérer les paramètres', 'tenant'),
  ('members.read', 'core', 'Voir les membres', 'tenant'),
  ('members.manage', 'core', 'Gérer les membres', 'tenant'),
  ('invitations.manage', 'core', 'Gérer les invitations', 'tenant'),
  ('licenses.read', 'core', 'Voir l''abonnement et les quotas', 'tenant'),
  ('licenses.request', 'core', 'Demander une extension de licence', 'tenant'),
  ('billing.manage', 'core', 'Gérer la facturation', 'tenant'),
  ('products.read', 'products', 'Voir les produits', 'tenant'),
  ('products.write', 'products', 'Créer/modifier les produits', 'tenant'),
  ('products.delete', 'products', 'Supprimer les produits', 'tenant'),
  ('websites.read', 'websites', 'Voir les sites', 'tenant'),
  ('websites.write', 'websites', 'Créer/modifier les sites', 'tenant'),
  ('connectors.read', 'connectors', 'Voir les connecteurs', 'tenant'),
  ('connectors.manage', 'connectors', 'Connecter/déconnecter', 'tenant'),
  ('scheduler.read', 'scheduler', 'Voir le scheduler', 'tenant'),
  ('scheduler.manage', 'scheduler', 'Configurer le scheduler', 'tenant'),
  ('reporting.read', 'reporting', 'Voir les rapports', 'tenant'),
  ('history.read', 'history', 'Consulter l''historique', 'tenant'),
  ('history.read_values', 'history', 'Voir les valeurs avant/après', 'tenant'),
  ('history.export', 'history', 'Exporter l''historique (CSV)', 'tenant'),
  ('platform.tenants.manage', 'core', 'PILOTE — gérer les tenants', 'platform'),
  ('platform.licenses.manage', 'core', 'PILOTE — gérer les licences', 'platform'),
  ('platform.health.read', 'core', 'PILOTE — System Health', 'platform'),
  ('platform.private_data.access', 'core', 'PILOTE — accès support aux données privées (audité)', 'platform')
ON CONFLICT DO NOTHING;

INSERT INTO public.role_permissions (role_id, permission_id)
SELECT r.id, p.id
  FROM public.tenant_roles r JOIN public.permissions p ON p.scope = 'tenant'
 WHERE r.tenant_id IS NULL AND (
       r.code = 'tenant_owner'
    OR (r.code = 'tenant_admin' AND p.code <> 'billing.manage')
    OR (r.code = 'tenant_member' AND (p.code LIKE '%.read' OR p.code IN ('products.write', 'websites.write', 'scheduler.manage', 'licenses.request')))
    OR (r.code = 'tenant_viewer' AND p.code LIKE '%.read' AND p.code NOT IN ('history.read')))
ON CONFLICT DO NOTHING;

-- Subscription plans (limits editable by the PILOTE)
INSERT INTO public.subscription_plans (code, name, is_trial, trial_duration_hours, price_monthly_cents, sort_order) VALUES
  ('DEMO', 'Démo', true, 72, 0, 0),
  ('STARTER', 'Starter', false, NULL, NULL, 10),
  ('GROWTH', 'Growth', false, NULL, NULL, 20),
  ('GROWTH_ENTREPRISE', 'Growth Entreprise', false, NULL, NULL, 30)
ON CONFLICT DO NOTHING;

INSERT INTO public.subscription_plan_quotas (plan_id, quota_code, limit_value, period)
SELECT p.id, q.code, CASE p.code WHEN 'DEMO' THEN q.demo WHEN 'STARTER' THEN q.starter
                                 WHEN 'GROWTH' THEN q.growth ELSE NULL END, q.period
  FROM public.subscription_plans p
 CROSS JOIN (VALUES
   ('scheduler.configurations', 3, 10, 50, 'none'),
   ('products.max', 1, 3, 10, 'none'),
   ('websites.max', 1, 3, 10, 'none'),
   ('members.max', 2, 5, 15, 'none'),
   ('connectors.max', 1, 5, 20, 'none'),
   ('ai.tokens.monthly', 100000, 2000000, 10000000, 'month')
 ) AS q(code, demo, starter, growth, period)
ON CONFLICT DO NOTHING;

INSERT INTO public.subscription_plan_features (plan_id, feature_id)
SELECT p.id, f.id
  FROM public.subscription_plans p
  JOIN public.platform_module_features f ON true
  JOIN public.platform_modules m ON m.id = f.module_id
 WHERE m.code = ANY (CASE p.code
   WHEN 'DEMO' THEN ARRAY['core','products','websites','scheduler','reporting','history','seo']
   WHEN 'STARTER' THEN ARRAY['core','products','websites','scheduler','reporting','history','seo','connectors','content']
   WHEN 'GROWTH' THEN ARRAY['core','products','websites','scheduler','reporting','history','seo','connectors','content',
                            'geo','social','prospects','email_center','opportunities']
   ELSE (SELECT array_agg(code) FROM public.platform_modules) END)
ON CONFLICT DO NOTHING;

-- System Health services & checks
INSERT INTO public.system_services (code, name, category, is_critical) VALUES
  ('postgres', 'PostgreSQL (Supabase)', 'database', true),
  ('supabase_auth', 'Supabase Auth', 'auth', true),
  ('supabase_storage', 'Supabase Storage', 'storage', true),
  ('api', 'Django API', 'api', true),
  ('redis', 'Redis', 'cache', true),
  ('celery_worker', 'Celery workers', 'worker', true),
  ('celery_beat', 'Celery Beat', 'scheduler', false),
  ('configuration', 'Configuration', 'configuration', true),
  ('connectors', 'Connecteurs', 'connector', false),
  ('ai_providers', 'Fournisseurs IA', 'ai_provider', false)
ON CONFLICT DO NOTHING;

INSERT INTO public.system_health_checks (service_id, code, name, check_type, interval_seconds)
SELECT s.id, c.code, c.name, c.type, c.interval
  FROM (VALUES
    ('postgres', 'db.connectivity', 'Connexion PostgreSQL', 'database', 60),
    ('postgres', 'db.migrations', 'Migrations appliquées', 'database', 3600),
    ('postgres', 'db.rls', 'RLS activée sur toutes les tables', 'database', 3600),
    ('postgres', 'db.indexes', 'Index invalides', 'database', 3600),
    ('supabase_auth', 'auth.health', 'Supabase Auth /health', 'http', 300),
    ('supabase_storage', 'storage.buckets', 'Buckets privés présents', 'http', 900),
    ('api', 'api.self', 'API /api/v1/health/live', 'http', 60),
    ('redis', 'redis.ping', 'Redis PING / SET / GET', 'redis', 60),
    ('celery_worker', 'celery.ping', 'Workers Celery (ping + heartbeat)', 'celery', 120),
    ('celery_beat', 'celery.beat', 'Heartbeat Celery Beat', 'celery', 300),
    ('configuration', 'config.env', 'Variables d''environnement requises', 'configuration', 3600)
  ) AS c(service, code, name, type, interval)
  JOIN public.system_services s ON s.code = c.service
ON CONFLICT DO NOTHING;

-- Retention defaults (platform level). 'keep' = never purged automatically.
INSERT INTO public.data_retention_policies (tenant_id, data_category, history_type, retention_days, archive_mode, deletion_rule) VALUES
  (NULL, 'audit_events', 'activity', 1825, 'storage_export', 'keep'),
  (NULL, 'entity_history', 'history', 1825, 'storage_export', 'keep'),
  (NULL, 'activity_events', 'activity', 730, 'none', 'delete'),
  (NULL, 'execution_logs', 'technical', 365, 'none', 'delete'),
  (NULL, 'application_logs', 'technical', 90, 'none', 'delete'),
  (NULL, 'system_health_results', 'technical', 90, 'none', 'delete'),
  (NULL, 'record_access_logs', 'activity', 365, 'none', 'delete'),
  (NULL, 'notifications', 'business', 180, 'none', 'delete'),
  (NULL, 'personal_data', 'business', 1095, 'none', 'anonymize')
ON CONFLICT DO NOTHING;

-- Reference catalogues
INSERT INTO public.identity_providers (code, name, protocol) VALUES
  ('google', 'Google Workspace', 'oidc'), ('microsoft', 'Microsoft Entra ID', 'oidc'), ('saml', 'SAML 2.0 générique', 'saml')
ON CONFLICT DO NOTHING;

INSERT INTO public.connector_providers (code, name, category, auth_type) VALUES
  ('google_analytics', 'Google Analytics 4', 'analytics', 'oauth2'),
  ('google_search_console', 'Google Search Console', 'seo', 'oauth2'),
  ('gmail', 'Gmail', 'email', 'oauth2'),
  ('outlook', 'Microsoft Outlook', 'email', 'oauth2'),
  ('hubspot', 'HubSpot', 'crm', 'oauth2'),
  ('linkedin', 'LinkedIn', 'social', 'oauth2'),
  ('wordpress', 'WordPress', 'cms', 'api_key'),
  ('sendgrid', 'SendGrid', 'email', 'api_key')
ON CONFLICT DO NOTHING;

INSERT INTO public.ai_providers (code, name) VALUES
  ('anthropic', 'Anthropic'), ('openai', 'OpenAI'), ('google', 'Google AI'), ('mistral', 'Mistral AI')
ON CONFLICT DO NOTHING;

INSERT INTO public.ai_crawler_registry (code, name, user_agent_pattern, operator) VALUES
  ('gptbot', 'GPTBot', 'GPTBot', 'OpenAI'),
  ('oai_searchbot', 'OAI-SearchBot', 'OAI-SearchBot', 'OpenAI'),
  ('claudebot', 'ClaudeBot', 'ClaudeBot', 'Anthropic'),
  ('perplexitybot', 'PerplexityBot', 'PerplexityBot', 'Perplexity'),
  ('google_extended', 'Google-Extended', 'Google-Extended', 'Google'),
  ('ccbot', 'CCBot', 'CCBot', 'Common Crawl')
ON CONFLICT DO NOTHING;

INSERT INTO public.notification_templates (code, channel, locale, subject, body) VALUES
  ('demo.welcome', 'email', 'fr', 'Bienvenue sur Growth IA', 'Votre espace démo est actif pour 72 heures.'),
  ('trial.expiring', 'email', 'fr', 'Votre démo expire bientôt', 'Votre période de démonstration se termine le {{expires_at}}.'),
  ('invitation.sent', 'email', 'fr', 'Invitation à rejoindre {{tenant_name}}', 'Vous avez été invité(e) à rejoindre {{tenant_name}} sur Growth IA.'),
  ('quota.threshold', 'in_app', 'fr', 'Quota bientôt atteint', 'Le quota {{quota_code}} a atteint {{threshold}} %.')
ON CONFLICT DO NOTHING;
