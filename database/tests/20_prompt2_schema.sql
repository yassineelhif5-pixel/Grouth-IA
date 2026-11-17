-- Growth IA — PROMPT 2 schema tests (run tables, business roles, new statuses, WhatsApp isolation). Rolled back.
\set ON_ERROR_STOP 1
BEGIN;
SET LOCAL client_min_messages = warning;
CREATE FUNCTION pg_temp.ok(cond boolean, msg text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN IF cond IS NOT TRUE THEN RAISE EXCEPTION 'FAIL: %', msg; END IF; RAISE NOTICE 'ok - %', msg; END $$;
SET LOCAL client_min_messages = notice;

DO $$ DECLARE a uuid := gen_random_uuid(); b uuid := gen_random_uuid(); BEGIN
  INSERT INTO auth.users (id, email, email_confirmed_at) VALUES (a, 'p2a-' || a || '@example.test', now()), (b, 'p2b-' || b || '@example.test', now());
  PERFORM set_config('t.a', a::text, true); PERFORM set_config('t.b', b::text, true);
END $$;
SET LOCAL ROLE app_backend;
SELECT app.set_context(current_setting('t.a')::uuid, NULL, gen_random_uuid(), NULL, 'user', false, NULL);
SELECT set_config('t.ta', app.provision_demo_tenant(current_setting('t.a')::uuid, 'P2A', 'p2a-' || left(current_setting('t.a'), 8))::text, true);
SELECT app.set_context(current_setting('t.b')::uuid, NULL, gen_random_uuid(), NULL, 'user', false, NULL);
SELECT set_config('t.tb', app.provision_demo_tenant(current_setting('t.b')::uuid, 'P2B', 'p2b-' || left(current_setting('t.b'), 8))::text, true);

-- run tables: status transitions allowed, deletion forbidden
SELECT app.set_context(current_setting('t.a')::uuid, current_setting('t.ta')::uuid, gen_random_uuid(), NULL, 'user', false, NULL);
DO $$ DECLARE p uuid; s uuid; au uuid; BEGIN
  INSERT INTO products (tenant_id, name, slug) VALUES (current_setting('t.ta')::uuid, 'P', 'p') RETURNING id INTO p;
  INSERT INTO seo_projects (tenant_id, product_id, name) VALUES (current_setting('t.ta')::uuid, p, 'SEO') RETURNING id INTO s;
  INSERT INTO seo_audits (tenant_id, project_id, status) VALUES (current_setting('t.ta')::uuid, s, 'queued') RETURNING id INTO au;
  UPDATE seo_audits SET status = 'running' WHERE id = au;
  UPDATE seo_audits SET status = 'succeeded', score = 72 WHERE id = au;
  PERFORM set_config('t.audit', au::text, true);
  PERFORM set_config('t.prod', p::text, true);
END $$;
SELECT pg_temp.ok((SELECT status = 'succeeded' AND updated_at >= created_at FROM seo_audits WHERE id = current_setting('t.audit')::uuid), 'run table accepts status transitions');
DO $$ BEGIN DELETE FROM seo_audits WHERE id = current_setting('t.audit')::uuid; RAISE EXCEPTION 'FAIL: run deleted';
EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'ok - run rows cannot be deleted'; END $$;

-- new statuses
INSERT INTO market_opportunities (tenant_id, title, status, product_id) VALUES (current_setting('t.ta')::uuid, 'O', 'under_analysis', current_setting('t.prod')::uuid);
DO $$ BEGIN INSERT INTO market_opportunities (tenant_id, title, status) VALUES (current_setting('t.ta')::uuid, 'X', 'bogus');
  RAISE EXCEPTION 'FAIL: invalid status accepted';
EXCEPTION WHEN check_violation THEN RAISE NOTICE 'ok - opportunity statuses enforced'; END $$;
INSERT INTO prospects (tenant_id, status) VALUES (current_setting('t.ta')::uuid, 'demo_requested');
SELECT pg_temp.ok(true, 'pipeline status demo_requested accepted');

-- WhatsApp isolation
DO $$ DECLARE acc uuid; ct uuid; cv uuid; BEGIN
  INSERT INTO whatsapp_accounts (tenant_id, phone_number_id) VALUES (current_setting('t.ta')::uuid, '123') RETURNING id INTO acc;
  INSERT INTO whatsapp_contacts (tenant_id, wa_id, consent_status) VALUES (current_setting('t.ta')::uuid, '33600000000', 'opted_in') RETURNING id INTO ct;
  INSERT INTO whatsapp_conversations (tenant_id, account_id, contact_id) VALUES (current_setting('t.ta')::uuid, acc, ct) RETURNING id INTO cv;
  INSERT INTO whatsapp_messages (tenant_id, conversation_id, direction, body) VALUES (current_setting('t.ta')::uuid, cv, 'inbound', 'Bonjour');
END $$;
SELECT app.set_context(current_setting('t.b')::uuid, current_setting('t.tb')::uuid, gen_random_uuid(), NULL, 'user', false, NULL);
SELECT pg_temp.ok((SELECT count(*) FROM whatsapp_messages) = 0, 'tenant B backend cannot read tenant A WhatsApp');
RESET ROLE;
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', current_setting('t.b'), true);
SELECT pg_temp.ok((SELECT count(*) FROM whatsapp_conversations) = 0, 'user B cannot read tenant A WhatsApp conversations');
SELECT set_config('request.jwt.claim.sub', current_setting('t.a'), true);
SELECT pg_temp.ok((SELECT count(*) FROM whatsapp_messages) = 1, 'user A reads its WhatsApp messages');
RESET ROLE;

-- history on new tables, business roles
SELECT pg_temp.ok((SELECT count(*) FROM entity_history WHERE entity_type = 'whatsapp_messages') = 1, 'WhatsApp messages are versioned');
SELECT pg_temp.ok((SELECT count(*) FROM tenant_roles WHERE tenant_id IS NULL) >= 12, '12 system roles available');
DO $$ DECLARE r_sales uuid; r_content uuid; BEGIN
  SELECT id INTO r_sales FROM tenant_roles WHERE tenant_id IS NULL AND code = 'sales_rep';
  SELECT id INTO r_content FROM tenant_roles WHERE tenant_id IS NULL AND code = 'content_manager';
  PERFORM pg_temp.ok(EXISTS (SELECT 1 FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE rp.role_id = r_sales AND p.code = 'email.send'), 'sales_rep can send emails');
  PERFORM pg_temp.ok(NOT EXISTS (SELECT 1 FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE rp.role_id = r_sales AND p.code = 'content.publish'), 'sales_rep cannot publish content');
  PERFORM pg_temp.ok(EXISTS (SELECT 1 FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE rp.role_id = r_content AND p.code = 'content.approve'), 'content_manager can approve content');
END $$;
SELECT pg_temp.ok((SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND NOT c.relrowsecurity) = 0, 'RLS on every table (incl. new ones)');
DO $$ BEGIN RAISE NOTICE 'ALL PROMPT2 SQL TESTS PASSED'; END $$;
ROLLBACK;
