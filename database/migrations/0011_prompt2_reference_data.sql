-- Growth IA — Migration 0011 — PROMPT 2 reference data (additive, idempotent)

-- ── New platform modules ──
INSERT INTO public.platform_modules (code, name, category, is_core, sort_order) VALUES
  ('pages', 'Page Builder', 'growth', false, 125),
  ('video', 'Video Studio', 'growth', false, 135),
  ('social_hunter', 'Social Opportunity Hunter', 'growth', false, 145),
  ('whatsapp', 'WhatsApp Center', 'growth', false, 165),
  ('crm', 'CRM', 'growth', false, 168),
  ('workflows', 'Workflows & Automation', 'growth', false, 175)
ON CONFLICT DO NOTHING;
INSERT INTO public.platform_module_features (module_id, code, name)
SELECT m.id, m.code || '.access', 'Accès ' || m.name FROM public.platform_modules m
ON CONFLICT DO NOTHING;

INSERT INTO public.subscription_plan_features (plan_id, feature_id)
SELECT p.id, f.id FROM public.subscription_plans p
  JOIN public.platform_module_features f ON true JOIN public.platform_modules m ON m.id = f.module_id
 WHERE m.code = ANY (CASE p.code
   WHEN 'DEMO' THEN ARRAY['crm']
   WHEN 'STARTER' THEN ARRAY['pages','crm']
   WHEN 'GROWTH' THEN ARRAY['pages','video','social_hunter','whatsapp','crm','workflows']
   ELSE (SELECT array_agg(code) FROM public.platform_modules) END)
ON CONFLICT DO NOTHING;

-- ── New quotas (editable by the PILOTE) ──
INSERT INTO public.subscription_plan_quotas (plan_id, quota_code, limit_value, period)
SELECT p.id, q.code, CASE p.code WHEN 'DEMO' THEN q.demo WHEN 'STARTER' THEN q.starter WHEN 'GROWTH' THEN q.growth ELSE NULL END, q.period
  FROM public.subscription_plans p CROSS JOIN (VALUES
   ('seo.audits.monthly', 5, 30, 200, 'month'),
   ('seo.pages_per_audit', 25, 200, 1000, 'none'),
   ('geo.queries.monthly', 20, 200, 2000, 'month'),
   ('content.generations.monthly', 10, 100, 1000, 'month'),
   ('email.sends.daily', 20, 200, 2000, 'day'),
   ('whatsapp.sends.daily', 0, 50, 500, 'day'),
   ('prospects.max', 50, 1000, 20000, 'none'),
   ('workflows.max', 1, 5, 50, 'none'),
   ('ai.budget.monthly_cents', 500, 5000, 50000, 'month')
 ) AS q(code, demo, starter, growth, period)
ON CONFLICT DO NOTHING;

-- ── Business roles ──
INSERT INTO public.tenant_roles (tenant_id, code, name, description, is_system) VALUES
  (NULL, 'tenant_manager', 'Tenant Manager', 'Pilote l''activité du tenant (sans facturation)', true),
  (NULL, 'marketing_manager', 'Marketing Manager', 'SEO, GEO, contenus, social, campagnes', true),
  (NULL, 'seo_manager', 'SEO Manager', 'SEO et GEO', true),
  (NULL, 'content_manager', 'Content Manager', 'Contenus, pages, vidéos, validation', true),
  (NULL, 'social_media_manager', 'Social Media Manager', 'Publications sociales', true),
  (NULL, 'sales_manager', 'Sales Manager', 'Prospection, campagnes, CRM, équipe commerciale', true),
  (NULL, 'sales_rep', 'Sales Representative', 'Prospects affectés, emails, WhatsApp, CRM', true),
  (NULL, 'analyst', 'Analyst', 'Lecture et exports', true)
ON CONFLICT DO NOTHING;

-- ── Module permissions ──
INSERT INTO public.permissions (code, module_code, name, scope)
SELECT v.code, split_part(v.code, '.', 1), v.name, 'tenant' FROM (VALUES
  ('seo.read', 'Voir le SEO'), ('seo.manage', 'Lancer audits et gérer le SEO'),
  ('geo.read', 'Voir le GEO'), ('geo.manage', 'Gérer requêtes et analyses GEO'),
  ('content.read', 'Voir les contenus'), ('content.write', 'Créer/modifier des contenus'),
  ('content.approve', 'Valider des contenus'), ('content.publish', 'Publier des contenus'),
  ('pages.read', 'Voir les pages'), ('pages.write', 'Éditer les pages'), ('pages.publish', 'Publier des pages'),
  ('social.read', 'Voir le social'), ('social.write', 'Préparer des publications'), ('social.publish', 'Publier sur les réseaux'),
  ('video.read', 'Voir les vidéos'), ('video.write', 'Gérer les vidéos'),
  ('opportunities.read', 'Voir les opportunités'), ('opportunities.manage', 'Gérer les opportunités'),
  ('prospects.read', 'Voir les prospects'), ('prospects.write', 'Gérer les prospects'),
  ('campaigns.read', 'Voir les campagnes'), ('campaigns.manage', 'Gérer les campagnes'),
  ('email.read', 'Lire les emails'), ('email.send', 'Envoyer des emails'), ('email.manage', 'Gérer les boîtes mail'),
  ('whatsapp.read', 'Lire WhatsApp'), ('whatsapp.send', 'Envoyer WhatsApp'),
  ('crm.read', 'Voir le CRM'), ('crm.write', 'Modifier le CRM'),
  ('workflows.read', 'Voir les workflows'), ('workflows.manage', 'Gérer les workflows'),
  ('intelligence.read', 'Voir Growth Intelligence'), ('intelligence.manage', 'Décider des recommandations'),
  ('thor.use', 'Utiliser THOR'), ('approvals.decide', 'Valider les actions en attente'),
  ('reporting.export', 'Exporter les rapports'), ('ai.usage.read', 'Voir la consommation IA')
) AS v(code, name)
ON CONFLICT DO NOTHING;

INSERT INTO public.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM public.tenant_roles r JOIN public.permissions p ON p.scope = 'tenant'
 WHERE r.tenant_id IS NULL AND (
       r.code = 'tenant_owner'
    OR (r.code IN ('tenant_admin', 'tenant_manager') AND p.code <> 'billing.manage')
    OR (r.code = 'analyst' AND (p.code LIKE '%.read' OR p.code IN ('reporting.export', 'thor.use')))
    OR (r.code = 'tenant_member' AND (p.code LIKE '%.read' OR p.code IN ('thor.use')))
    OR (r.code = 'tenant_viewer' AND p.code LIKE '%.read' AND p.code NOT IN ('history.read', 'ai.usage.read'))
    OR (r.code = 'marketing_manager' AND (p.code LIKE '%.read' OR p.code IN ('seo.manage','geo.manage','content.write','content.approve',
        'content.publish','pages.write','pages.publish','social.write','social.publish','video.write','opportunities.manage',
        'campaigns.manage','workflows.manage','thor.use','approvals.decide','reporting.export','products.write','websites.write',
        'scheduler.manage')))
    OR (r.code = 'seo_manager' AND (p.code LIKE '%.read' OR p.code IN ('seo.manage','geo.manage','content.write','pages.write',
        'thor.use','scheduler.manage')))
    OR (r.code = 'content_manager' AND (p.code LIKE '%.read' OR p.code IN ('content.write','content.approve','content.publish',
        'pages.write','pages.publish','video.write','thor.use')))
    OR (r.code = 'social_media_manager' AND (p.code LIKE '%.read' OR p.code IN ('social.write','social.publish','content.write',
        'video.write','thor.use')))
    OR (r.code = 'sales_manager' AND (p.code LIKE '%.read' OR p.code IN ('prospects.write','campaigns.manage','email.send',
        'email.manage','whatsapp.send','crm.write','opportunities.manage','approvals.decide','thor.use','reporting.export')))
    OR (r.code = 'sales_rep' AND (p.code IN ('prospects.read','prospects.write','email.read','email.send','whatsapp.read',
        'whatsapp.send','crm.read','crm.write','opportunities.read','products.read','thor.use'))))
ON CONFLICT DO NOTHING;

-- ── Maximum automation capabilities (PILOTE) ──
INSERT INTO public.platform_action_capabilities (module_code, action_code, max_mode, description) VALUES
  ('seo', 'run_audit', 'automatic', 'Lancer un audit SEO'),
  ('geo', 'run_queries', 'automatic', 'Interroger les moteurs IA'),
  ('content', 'generate', 'automatic', 'Générer un contenu (brouillon)'),
  ('content', 'publish', 'approval', 'Publier un contenu sur un site'),
  ('pages', 'publish', 'approval', 'Publier une page CMS'),
  ('social', 'publish', 'approval', 'Publier sur un réseau social'),
  ('opportunities', 'hunt', 'automatic', 'Rechercher des opportunités'),
  ('social_hunter', 'listen', 'automatic', 'Veille des sources publiques'),
  ('prospects', 'send_campaign', 'approval', 'Envoyer une séquence de campagne'),
  ('email', 'auto_reply', 'approval', 'Envoyer automatiquement une réponse THOR'),
  ('whatsapp', 'send', 'approval', 'Envoyer un message WhatsApp'),
  ('crm', 'update_from_reply', 'automatic', 'Mettre à jour le CRM depuis une réponse'),
  ('workflows', 'run', 'approval', 'Exécuter un workflow'),
  ('intelligence', 'run_cycle', 'automatic', 'Cycle Growth Intelligence')
ON CONFLICT DO NOTHING;

-- ── Connector catalogue (secure integration gateway) ──
INSERT INTO public.connector_providers (code, name, category, auth_type, docs_status) VALUES
  ('smtp', 'SMTP (envoi)', 'email', 'smtp', 'available'),
  ('imap', 'IMAP (réception)', 'email', 'imap', 'available'),
  ('microsoft_graph', 'Microsoft Graph (Outlook / M365)', 'email', 'oauth2', 'available'),
  ('google_workspace', 'Google Workspace', 'email', 'oauth2', 'available'),
  ('brevo', 'Brevo', 'email', 'api_key', 'available'),
  ('mailgun', 'Mailgun', 'email', 'api_key', 'available'),
  ('amazon_ses', 'Amazon SES', 'email', 'api_key', 'not_implemented'),
  ('resend', 'Resend', 'email', 'api_key', 'available'),
  ('postmark', 'Postmark', 'email', 'api_key', 'available'),
  ('facebook', 'Facebook Pages', 'social', 'oauth2', 'available'),
  ('instagram', 'Instagram', 'social', 'oauth2', 'pending_approval'),
  ('youtube', 'YouTube', 'social', 'oauth2', 'pending_approval'),
  ('tiktok', 'TikTok', 'social', 'oauth2', 'pending_approval'),
  ('x', 'X', 'social', 'oauth2', 'pending_approval'),
  ('pinterest', 'Pinterest', 'social', 'oauth2', 'pending_approval'),
  ('reddit', 'Reddit', 'social', 'oauth2', 'available'),
  ('whatsapp_cloud', 'WhatsApp Business Cloud API', 'messaging', 'api_key', 'available'),
  ('telegram', 'Telegram', 'messaging', 'api_key', 'not_implemented'),
  ('messenger', 'Messenger', 'messaging', 'oauth2', 'not_implemented'),
  ('twilio', 'Twilio', 'messaging', 'api_key', 'not_implemented'),
  ('vonage', 'Vonage', 'messaging', 'api_key', 'not_implemented'),
  ('shopify', 'Shopify', 'cms', 'api_key', 'not_implemented'),
  ('webflow', 'Webflow', 'cms', 'api_key', 'not_implemented'),
  ('ghost', 'Ghost', 'cms', 'api_key', 'available'),
  ('drupal', 'Drupal', 'cms', 'basic', 'not_implemented'),
  ('rest_cms', 'API REST générique', 'cms', 'api_key', 'available'),
  ('pagespeed', 'PageSpeed Insights', 'seo', 'api_key', 'available'),
  ('bing_webmaster', 'Bing Webmaster Tools', 'seo', 'api_key', 'not_implemented'),
  ('clarity', 'Microsoft Clarity', 'analytics', 'api_key', 'not_implemented'),
  ('salesforce', 'Salesforce', 'crm', 'oauth2', 'not_implemented'),
  ('pipedrive', 'Pipedrive', 'crm', 'api_key', 'not_implemented'),
  ('zoho', 'Zoho CRM', 'crm', 'oauth2', 'not_implemented'),
  ('dynamics365', 'Dynamics 365', 'crm', 'oauth2', 'not_implemented'),
  ('odoo', 'Odoo', 'crm', 'api_key', 'not_implemented'),
  ('stripe', 'Stripe', 'payments', 'api_key', 'available'),
  ('paypal', 'PayPal', 'payments', 'oauth2', 'not_implemented'),
  ('paddle', 'Paddle', 'payments', 'api_key', 'not_implemented'),
  ('mollie', 'Mollie', 'payments', 'api_key', 'not_implemented'),
  ('s3', 'Amazon S3', 'storage', 'api_key', 'not_implemented'),
  ('azure_blob', 'Azure Blob', 'storage', 'api_key', 'not_implemented'),
  ('onedrive', 'OneDrive / SharePoint', 'storage', 'oauth2', 'not_implemented')
ON CONFLICT DO NOTHING;
UPDATE public.connector_providers SET docs_status = 'available'
 WHERE code IN ('google_analytics', 'google_search_console', 'gmail', 'outlook', 'hubspot', 'linkedin', 'wordpress', 'sendgrid')
   AND docs_status <> 'available';
UPDATE public.connector_providers SET category = 'social', auth_type = 'oauth2' WHERE code = 'linkedin';

-- ── AI providers (models & prices are configured by the PILOTE — never assumed) ──
INSERT INTO public.ai_providers (code, name, api_style) VALUES
  ('azure_openai', 'Azure OpenAI', 'azure_openai'), ('cohere', 'Cohere', 'cohere'),
  ('groq', 'Groq', 'openai'), ('ollama', 'Ollama', 'ollama'), ('perplexity', 'Perplexity', 'openai')
ON CONFLICT DO NOTHING;
UPDATE public.ai_providers SET api_style = 'anthropic' WHERE code = 'anthropic' AND api_style <> 'anthropic';
UPDATE public.ai_providers SET api_style = 'gemini' WHERE code = 'google' AND api_style <> 'gemini';

-- ── AI crawlers: purpose (crawl ≠ search ≠ training ≠ user fetch) ──
INSERT INTO public.ai_crawler_registry (code, name, user_agent_pattern, operator, purpose) VALUES
  ('chatgpt_user', 'ChatGPT-User', 'ChatGPT-User', 'OpenAI', 'user_fetch'),
  ('claude_searchbot', 'Claude-SearchBot', 'Claude-SearchBot', 'Anthropic', 'search'),
  ('claude_user', 'Claude-User', 'Claude-User', 'Anthropic', 'user_fetch'),
  ('googlebot', 'Googlebot', 'Googlebot', 'Google', 'crawl'),
  ('bingbot', 'Bingbot', 'bingbot', 'Microsoft', 'crawl')
ON CONFLICT DO NOTHING;
UPDATE public.ai_crawler_registry SET purpose = v.purpose FROM (VALUES
  ('gptbot', 'training'), ('oai_searchbot', 'search'), ('claudebot', 'training'),
  ('perplexitybot', 'search'), ('google_extended', 'training'), ('ccbot', 'training')) v(code, purpose)
 WHERE ai_crawler_registry.code = v.code AND ai_crawler_registry.purpose <> v.purpose;

-- ── System Health: new probes ──
INSERT INTO public.system_services (code, name, category, is_critical) VALUES
  ('email_send', 'Email — envoi', 'connector', false),
  ('email_receive', 'Email — réception', 'connector', false),
  ('webhooks', 'Webhooks entrants', 'api', false),
  ('whatsapp', 'WhatsApp Cloud API', 'connector', false),
  ('cms', 'CMS (WordPress…)', 'connector', false),
  ('social_apis', 'APIs sociales', 'connector', false),
  ('scheduler', 'Multi-Scheduler', 'scheduler', true)
ON CONFLICT DO NOTHING;
INSERT INTO public.system_health_checks (service_id, code, name, check_type, interval_seconds)
SELECT s.id, c.code, c.name, c.type, c.interval FROM (VALUES
  ('ai_providers', 'ai.providers', 'Fournisseurs IA configurés (appel réel)', 'ai', 3600),
  ('email_send', 'email.send', 'Boîtes mail — envoi (dernier test réel)', 'connector', 3600),
  ('email_receive', 'email.receive', 'Boîtes mail — réception / synchronisation', 'connector', 900),
  ('webhooks', 'webhooks.recent', 'Webhooks entrants (signatures, erreurs)', 'database', 900),
  ('whatsapp', 'whatsapp.accounts', 'Comptes WhatsApp', 'connector', 3600),
  ('cms', 'cms.wordpress', 'Connexions CMS', 'connector', 3600),
  ('social_apis', 'social.accounts', 'Comptes sociaux', 'connector', 3600),
  ('scheduler', 'scheduler.lag', 'Programmations en retard', 'database', 300),
  ('connectors', 'connectors.status', 'Statut des connecteurs', 'database', 900)
) AS c(service, code, name, type, interval) JOIN public.system_services s ON s.code = c.service
ON CONFLICT DO NOTHING;

INSERT INTO public.notification_templates (code, channel, locale, subject, body) VALUES
  ('opportunity.new', 'in_app', 'fr', 'Nouvelle opportunité', '{{title}}'),
  ('prospect.qualified', 'in_app', 'fr', 'Prospect qualifié', '{{name}}'),
  ('email.reply', 'in_app', 'fr', 'Nouvelle réponse', '{{subject}}'),
  ('email.demo_requested', 'in_app', 'fr', 'Demande de démo', '{{subject}}'),
  ('publication.succeeded', 'in_app', 'fr', 'Publication réussie', '{{title}}'),
  ('publication.failed', 'in_app', 'fr', 'Publication échouée', '{{title}}'),
  ('scheduler.failed', 'in_app', 'fr', 'Erreur Scheduler', '{{name}}'),
  ('report.ready', 'in_app', 'fr', 'Rapport disponible', '{{title}}'),
  ('connector.incident', 'in_app', 'fr', 'Incident connecteur', '{{provider}}'),
  ('approval.requested', 'in_app', 'fr', 'Validation requise', '{{action}}')
ON CONFLICT DO NOTHING;
