-- Growth IA — SQL integration tests: RLS, multi-tenant isolation, traceability, provisioning.
-- Fully non-destructive: everything runs in one transaction that is ROLLED BACK.
-- Runs on the local Supabase emulation (CI) and directly on the Supabase project.
\set ON_ERROR_STOP 1
BEGIN;
SET LOCAL client_min_messages = warning;

CREATE FUNCTION pg_temp.ok(cond boolean, msg text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  IF cond IS NOT TRUE THEN RAISE EXCEPTION 'FAIL: %', msg; END IF;
  RAISE NOTICE 'ok - %', msg;
END $$;
CREATE FUNCTION pg_temp.g(k text) RETURNS uuid LANGUAGE sql AS $$ SELECT current_setting('test.' || k)::uuid $$;
SET LOCAL client_min_messages = notice;

-- ── Fixtures: three verified users + one unverified ──
DO $$
DECLARE a uuid := gen_random_uuid(); b uuid := gen_random_uuid(); p uuid := gen_random_uuid(); u uuid := gen_random_uuid();
BEGIN
  INSERT INTO auth.users (id, email, email_confirmed_at) VALUES
    (a, 'test-a-' || a || '@example.test', now()), (b, 'test-b-' || b || '@example.test', now()),
    (p, 'test-p-' || p || '@example.test', now()), (u, 'test-u-' || u || '@example.test', NULL);
  INSERT INTO public.user_profiles (id, email, platform_role_code) VALUES (p, 'pilot@example.test', 'PILOTE');
  PERFORM set_config('test.a', a::text, true); PERFORM set_config('test.b', b::text, true);
  PERFORM set_config('test.p', p::text, true); PERFORM set_config('test.u', u::text, true);
  PERFORM set_config('test.corr', gen_random_uuid()::text, true);
END $$;

-- 1. RLS everywhere
SELECT pg_temp.ok(NOT EXISTS (
  SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relrowsecurity), 'RLS enabled on every public table and partition');

-- 2. DEMO provisioning (as Django backend role)
SET LOCAL ROLE app_backend;
SELECT app.set_context(pg_temp.g('a'), NULL, pg_temp.g('corr'), NULL, 'user', false, NULL);
SELECT set_config('test.ta', app.provision_demo_tenant(pg_temp.g('a'), 'Tenant A', 'tenant-a-' || substr(pg_temp.g('a')::text, 1, 8))::text, true);
SELECT app.set_context(pg_temp.g('b'), NULL, gen_random_uuid(), NULL, 'user', false, NULL);
SELECT set_config('test.tb', app.provision_demo_tenant(pg_temp.g('b'), 'Tenant B', 'tenant-b-' || substr(pg_temp.g('b')::text, 1, 8))::text, true);
DO $$ BEGIN
  PERFORM app.provision_demo_tenant(current_setting('test.a')::uuid, 'Again', 'again-' || substr(current_setting('test.a'), 1, 8));
  RAISE EXCEPTION 'FAIL: second DEMO provisioning allowed';
EXCEPTION WHEN unique_violation THEN RAISE NOTICE 'ok - only one DEMO tenant per user';
END $$;
DO $$ BEGIN
  PERFORM app.provision_demo_tenant(current_setting('test.u')::uuid, 'Unverified', 'unverified-x');
  RAISE EXCEPTION 'FAIL: unverified e-mail provisioned';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'ok - unverified e-mail rejected';
END $$;
RESET ROLE;
SELECT pg_temp.ok((SELECT status = 'trialing' AND trial_ends_at BETWEEN now() + interval '47 hours' AND now() + interval '49 hours'
                     FROM tenant_subscriptions WHERE tenant_id = pg_temp.g('ta')), 'DEMO subscription trialing for 48h (2-day free trial)');
SELECT pg_temp.ok((SELECT limit_value = 3 FROM tenant_license_quotas WHERE tenant_id = pg_temp.g('ta') AND quota_code = 'scheduler.configurations'),
                  'DEMO limited to 3 scheduler configurations');
SELECT pg_temp.ok(app.has_tenant_role(pg_temp.g('ta'), pg_temp.g('a'), ARRAY['tenant_owner']), 'signup user is tenant owner');
SELECT pg_temp.ok(app.has_permission(pg_temp.g('ta'), pg_temp.g('a'), 'history.export'), 'owner has history.export permission');
SELECT pg_temp.ok(NOT app.has_permission(pg_temp.g('ta'), pg_temp.g('b'), 'products.read'), 'user B has no permission in tenant A');
SELECT pg_temp.ok((SELECT count(*) >= 2 FROM audit_events WHERE tenant_id = pg_temp.g('ta') AND correlation_id = pg_temp.g('corr')),
                  'provisioning audit events share the correlation_id');
SELECT pg_temp.ok((SELECT count(*) FROM entity_history WHERE entity_type = 'tenants' AND entity_id = pg_temp.g('ta')) = 1,
                  'tenant creation versioned in entity_history');

-- 3. Versioned history of a business entity, author & correlation from the Django context
SET LOCAL ROLE app_backend;
SELECT app.set_context(pg_temp.g('a'), pg_temp.g('ta'), pg_temp.g('corr'), gen_random_uuid(), 'user', false, 'unit test');
DO $$ DECLARE v uuid; BEGIN
  INSERT INTO products (tenant_id, name, slug) VALUES (current_setting('test.ta')::uuid, 'Prod A', 'prod-a') RETURNING id INTO v;
  PERFORM set_config('test.prod', v::text, true);
END $$;
UPDATE products SET name = 'Prod A v2' WHERE id = pg_temp.g('prod');
UPDATE products SET name = 'Prod A v2' WHERE id = pg_temp.g('prod');  -- no-op: must not create a version
UPDATE products SET deleted_at = now() WHERE id = pg_temp.g('prod');
UPDATE products SET deleted_at = NULL WHERE id = pg_temp.g('prod');
SELECT pg_temp.ok((SELECT version_number FROM products WHERE id = pg_temp.g('prod')) = 4, 'version_number bumped to 4 (no-op ignored)');
SELECT pg_temp.ok((SELECT created_by = pg_temp.g('a') FROM products WHERE id = pg_temp.g('prod')), 'created_by filled from context');
RESET ROLE;
SELECT pg_temp.ok((SELECT string_agg(operation, ',' ORDER BY version_number) FROM entity_history WHERE entity_id = pg_temp.g('prod'))
                  = 'INSERT,UPDATE,SOFT_DELETE,RESTORE', 'history operations INSERT,UPDATE,SOFT_DELETE,RESTORE');
SELECT pg_temp.ok((SELECT previous_data->>'name' = 'Prod A' AND current_data->>'name' = 'Prod A v2' AND changed_fields = ARRAY['name']
                     AND changed_by = pg_temp.g('a') AND correlation_id = pg_temp.g('corr') AND change_reason = 'unit test'
                     FROM entity_history WHERE entity_id = pg_temp.g('prod') AND version_number = 2),
                  'history keeps before/after, changed fields, author, reason, correlation_id');

-- 4. Secrets never reach history
SET LOCAL ROLE app_backend;
SELECT app.set_context(pg_temp.g('a'), pg_temp.g('ta'), gen_random_uuid(), NULL, 'user', false, NULL);
INSERT INTO tenant_domains (tenant_id, domain, verification_token) VALUES (pg_temp.g('ta'), 'a.example.test', 'super-secret-token');
RESET ROLE;
SELECT pg_temp.ok((SELECT NOT (current_data ? 'verification_token') FROM entity_history
                    WHERE entity_type = 'tenant_domains' AND tenant_id = pg_temp.g('ta')), 'secret column excluded from history');

-- 5. Immutable journals
SET LOCAL ROLE app_backend;
DO $$ BEGIN UPDATE audit_events SET description = 'tampered'; RAISE EXCEPTION 'FAIL: audit_events updatable';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'ok - backend cannot update audit_events'; END $$;
DO $$ BEGIN DELETE FROM entity_history; RAISE EXCEPTION 'FAIL: entity_history deletable';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'ok - backend cannot delete entity_history'; END $$;
RESET ROLE;
DO $$ BEGIN UPDATE audit_events SET description = 'tampered' WHERE tenant_id = current_setting('test.ta')::uuid;
  RAISE EXCEPTION 'FAIL: owner could tamper audit_events';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'ok - append-only trigger blocks even the table owner'; END $$;

-- 6. tenant_id immutable
SET LOCAL ROLE app_backend;
SELECT app.set_context(NULL, NULL, NULL, NULL, 'system', true, NULL);
DO $$ BEGIN UPDATE products SET tenant_id = current_setting('test.tb')::uuid WHERE id = current_setting('test.prod')::uuid;
  RAISE EXCEPTION 'FAIL: tenant_id changed';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'ok - tenant_id is immutable'; END $$;

-- 7. Backend RLS: tenant context enforced by the database
SELECT app.set_context(pg_temp.g('b'), pg_temp.g('tb'), gen_random_uuid(), NULL, 'user', false, NULL);
INSERT INTO products (tenant_id, name, slug) VALUES (pg_temp.g('tb'), 'Prod B', 'prod-b');
DO $$ BEGIN
  INSERT INTO products (tenant_id, name, slug) VALUES (current_setting('test.ta')::uuid, 'Intrusion', 'intrusion');
  RAISE EXCEPTION 'FAIL: backend wrote into another tenant';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'ok - backend context cannot write into another tenant'; END $$;
SELECT pg_temp.ok((SELECT count(*) FROM products WHERE tenant_id = pg_temp.g('ta')) = 0, 'backend context B cannot read tenant A products');
SELECT pg_temp.ok((SELECT count(*) FROM entity_history WHERE tenant_id = pg_temp.g('ta')) = 0, 'backend context B cannot read tenant A history');
RESET ROLE;

-- 8. End-user RLS (Supabase JWT, role authenticated)
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', pg_temp.g('a')::text, true);
SELECT pg_temp.ok((SELECT count(*) FROM tenants) = 1, 'user A sees only its tenant');
SELECT pg_temp.ok((SELECT count(*) FROM products WHERE tenant_id = pg_temp.g('tb')) = 0, 'user A cannot read tenant B products');
SELECT pg_temp.ok((SELECT count(*) FROM products) = 1, 'user A reads its own products');
SELECT pg_temp.ok((SELECT count(*) FROM entity_history WHERE tenant_id = pg_temp.g('tb')) = 0, 'user A cannot read tenant B history');
SELECT pg_temp.ok((SELECT count(*) FROM entity_history WHERE tenant_id = pg_temp.g('ta')) > 0, 'tenant owner A reads its tenant history');
SELECT pg_temp.ok((SELECT count(*) FROM audit_events WHERE tenant_id = pg_temp.g('tb')) = 0, 'user A cannot read tenant B audit events');
SELECT pg_temp.ok((SELECT count(*) FROM invitation_tokens) = 0, 'invitation tokens never readable by end users');
DO $$ BEGIN INSERT INTO products (tenant_id, name, slug) VALUES (current_setting('test.ta')::uuid, 'x', 'x');
  RAISE EXCEPTION 'FAIL: end user wrote directly';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'ok - end users cannot write directly (writes go through Django)'; END $$;
SELECT set_config('request.jwt.claim.sub', pg_temp.g('p')::text, true);
SELECT pg_temp.ok((SELECT count(*) FROM tenants WHERE id IN (pg_temp.g('ta'), pg_temp.g('tb'))) = 2, 'PILOTE sees all tenants');
SELECT pg_temp.ok((SELECT count(*) FROM products WHERE tenant_id IN (pg_temp.g('ta'), pg_temp.g('tb'))) = 0,
                  'PILOTE has no blanket access to private business data');
SELECT pg_temp.ok((SELECT count(*) FROM audit_events WHERE tenant_id = pg_temp.g('tb')) > 0, 'PILOTE reads audit events');
RESET ROLE;
SET LOCAL ROLE anon;
DO $$ BEGIN PERFORM 1 FROM products; RAISE EXCEPTION 'FAIL: anon can read products';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'ok - anon has no access'; END $$;
RESET ROLE;

-- 9. Composite foreign keys forbid cross-tenant references (even for privileged writers)
DO $$ BEGIN
  INSERT INTO websites (tenant_id, product_id, url) VALUES (current_setting('test.tb')::uuid, current_setting('test.prod')::uuid, 'https://x.test');
  RAISE EXCEPTION 'FAIL: cross-tenant FK accepted';
EXCEPTION WHEN foreign_key_violation THEN RAISE NOTICE 'ok - cross-tenant reference rejected by composite FK'; END $$;

-- 10. Controlled journal correction & retention
SET LOCAL ROLE app_backend;
SELECT app.set_context(pg_temp.g('p'), NULL, gen_random_uuid(), NULL, 'pilot', false, NULL);
DO $$ BEGIN
  PERFORM app.correct_log_entry('audit_events', (SELECT id FROM audit_events WHERE tenant_id = current_setting('test.ta')::uuid LIMIT 1), '{"description":"x"}', 'r');
  RAISE EXCEPTION 'FAIL: correction without platform scope';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'ok - correction requires platform scope'; END $$;
SELECT app.set_context(pg_temp.g('p'), NULL, gen_random_uuid(), NULL, 'pilot', true, NULL);
SELECT app.correct_log_entry('audit_events', (SELECT id FROM audit_events WHERE tenant_id = pg_temp.g('ta') AND action = 'tenant.provisioned'),
                             '{"description":"DEMO tenant created by signup (corrected)"}', 'typo fix');
SELECT pg_temp.ok((SELECT count(*) FROM audit_log_corrections WHERE reason = 'typo fix') = 1
                  AND (SELECT count(*) FROM audit_events WHERE action = 'journal.corrected') >= 1, 'correction recorded and audited');
INSERT INTO application_logs (level, logger, message, created_at) VALUES ('info', 'test', 'old', now() - interval '200 days');
INSERT INTO application_logs (level, logger, message) VALUES ('info', 'test', 'recent');
SELECT pg_temp.ok(app.purge_expired('application_logs') >= 1, 'retention purge deletes expired technical logs');
SELECT pg_temp.ok((SELECT count(*) FROM application_logs WHERE logger = 'test') = 1, 'recent logs kept');
SELECT pg_temp.ok(app.purge_expired('audit_events') = 0, 'audit_events policy = keep → nothing purged');
SELECT pg_temp.ok(app.purge_expired('products') = 0, 'no policy → never deleted');

-- 11. Licence job
UPDATE tenant_subscriptions SET trial_ends_at = now() - interval '1 minute' WHERE tenant_id = pg_temp.g('tb');
SELECT pg_temp.ok(app.expire_trials() >= 1, 'expire_trials expires finished trials');
RESET ROLE;
SELECT pg_temp.ok((SELECT status = 'expired' FROM tenant_subscriptions WHERE tenant_id = pg_temp.g('tb')), 'subscription B expired');
SELECT pg_temp.ok((SELECT status = 'trialing' FROM tenant_subscriptions WHERE tenant_id = pg_temp.g('ta')), 'subscription A untouched');
SELECT pg_temp.ok((SELECT count(*) FROM tenant_subscription_history WHERE tenant_id = pg_temp.g('tb') AND event_type = 'expired') = 1,
                  'expiry written in subscription history');

SET LOCAL client_min_messages = notice;
DO $$ BEGIN RAISE NOTICE 'ALL SQL TESTS PASSED'; END $$;
ROLLBACK;
