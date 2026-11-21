-- Forced correction: access to the client's site source (GitHub repository) to replace files directly.
-- Additive and idempotent.
INSERT INTO public.connector_providers (code, name, category, auth_type, docs_status)
VALUES ('github', 'GitHub (dépôt du site)', 'cms', 'oauth2', 'available')
ON CONFLICT DO NOTHING;
