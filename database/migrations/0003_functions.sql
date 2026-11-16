-- Growth IA — Migration 0003 — security helpers & traceability trigger functions

-- ───────────── Security helpers (SECURITY DEFINER: evaluated without RLS recursion) ─────────────
CREATE OR REPLACE FUNCTION app.is_platform_admin() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.user_profiles p
     WHERE p.id = (SELECT auth.uid()) AND p.platform_role_code = 'PILOTE'
       AND p.status = 'active' AND p.deleted_at IS NULL)
$$;

CREATE OR REPLACE FUNCTION app.is_member_of(p_tenant uuid, p_user uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT p_user IS NOT NULL AND EXISTS (
    SELECT 1 FROM public.tenant_members m JOIN public.tenants t ON t.id = m.tenant_id
     WHERE m.tenant_id = p_tenant AND m.user_id = p_user AND m.status = 'active'
       AND m.deleted_at IS NULL AND t.deleted_at IS NULL AND t.status <> 'archived')
$$;

CREATE OR REPLACE FUNCTION app.is_tenant_member(p_tenant uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT app.is_member_of(p_tenant, (SELECT auth.uid()))
$$;

-- Used only in policies attached TO app_backend: the user comes from the Django context.
CREATE OR REPLACE FUNCTION app.backend_user_is_member(p_tenant uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT app.is_member_of(p_tenant, app._guc_uuid('app.user_id'))
$$;

CREATE OR REPLACE FUNCTION app.has_tenant_role(p_tenant uuid, p_user uuid, p_roles text[]) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.tenant_members m
      JOIN public.tenant_memberships ms ON ms.member_id = m.id AND ms.tenant_id = m.tenant_id
      JOIN public.tenant_roles r ON r.id = ms.role_id
     WHERE m.tenant_id = p_tenant AND m.user_id = p_user AND m.status = 'active' AND m.deleted_at IS NULL
       AND ms.deleted_at IS NULL AND ms.valid_from <= now() AND (ms.valid_until IS NULL OR ms.valid_until > now())
       AND r.code = ANY (p_roles))
$$;

CREATE OR REPLACE FUNCTION app.is_tenant_admin(p_tenant uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT p_tenant IS NOT NULL AND app.has_tenant_role(p_tenant, (SELECT auth.uid()), ARRAY['tenant_owner', 'tenant_admin'])
$$;

-- Effective permission = explicit deny > explicit allow > role grants.
CREATE OR REPLACE FUNCTION app.has_permission(p_tenant uuid, p_user uuid, p_permission text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  WITH m AS (
    SELECT id FROM public.tenant_members
     WHERE tenant_id = p_tenant AND user_id = p_user AND status = 'active' AND deleted_at IS NULL),
  perm AS (SELECT id FROM public.permissions WHERE code = p_permission),
  overrides AS (
    SELECT up.effect FROM public.user_permissions up, m, perm
     WHERE up.tenant_id = p_tenant AND up.member_id = m.id AND up.permission_id = perm.id
       AND up.deleted_at IS NULL AND (up.expires_at IS NULL OR up.expires_at > now()))
  SELECT CASE
    WHEN NOT EXISTS (SELECT 1 FROM m) THEN false
    WHEN EXISTS (SELECT 1 FROM overrides WHERE effect = 'deny') THEN false
    WHEN EXISTS (SELECT 1 FROM overrides WHERE effect = 'allow') THEN true
    ELSE EXISTS (
      SELECT 1 FROM m
        JOIN public.tenant_memberships ms ON ms.member_id = m.id AND ms.tenant_id = p_tenant
         AND ms.deleted_at IS NULL AND (ms.valid_until IS NULL OR ms.valid_until > now())
        JOIN public.role_permissions rp ON rp.role_id = ms.role_id
        JOIN perm ON perm.id = rp.permission_id)
  END
$$;

-- ───────────── Trigger: fill context columns on INSERT ─────────────
CREATE OR REPLACE FUNCTION app.tg_fill_context() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  j jsonb := to_jsonb(NEW);
  p jsonb := '{}'::jsonb;
  uid uuid := app.current_user_id();
  cid uuid := app.current_correlation_id();
BEGIN
  IF j ? 'correlation_id' AND j->>'correlation_id' IS NULL AND cid IS NOT NULL THEN
    p := p || jsonb_build_object('correlation_id', cid);
  END IF;
  IF j ? 'created_by' AND j->>'created_by' IS NULL AND uid IS NOT NULL
     AND EXISTS (SELECT 1 FROM auth.users u WHERE u.id = uid) THEN
    p := p || jsonb_build_object('created_by', uid, 'updated_by', uid);
  END IF;
  IF TG_NARGS > 0 AND TG_ARGV[0] = 'versioned' THEN p := p || '{"version_number": 1}'::jsonb; END IF;
  IF j ? 'created_at' THEN p := p || jsonb_build_object('created_at', coalesce((j->>'created_at')::timestamptz, now())); END IF;
  IF p <> '{}'::jsonb THEN NEW := jsonb_populate_record(NEW, p); END IF;
  RETURN NEW;
END $$;

-- ───────────── Trigger: touch updated_at/updated_by, bump version, protect identity columns ─────────────
CREATE OR REPLACE FUNCTION app.tg_touch() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  n jsonb := to_jsonb(NEW);
  o jsonb := to_jsonb(OLD);
  meta text[] := ARRAY['updated_at', 'updated_by', 'version_number', 'correlation_id'];
  p jsonb;
  uid uuid := app.current_user_id();
BEGIN
  IF n->'id' IS DISTINCT FROM o->'id' THEN
    RAISE EXCEPTION 'id is immutable on %', TG_TABLE_NAME USING ERRCODE = '42501';
  END IF;
  IF n ? 'tenant_id' AND n->'tenant_id' IS DISTINCT FROM o->'tenant_id' THEN
    RAISE EXCEPTION 'tenant_id is immutable on %', TG_TABLE_NAME USING ERRCODE = '42501';
  END IF;
  IF (n - meta) = (o - meta) THEN
    RETURN NEW;  -- no-op update: no new version
  END IF;
  p := jsonb_build_object('updated_at', clock_timestamp());
  IF n ? 'updated_by' AND uid IS NOT NULL AND EXISTS (SELECT 1 FROM auth.users u WHERE u.id = uid) THEN
    p := p || jsonb_build_object('updated_by', uid);
  END IF;
  IF n ? 'version_number' THEN
    p := p || jsonb_build_object('version_number', (o->>'version_number')::int + 1);
  END IF;
  IF n ? 'correlation_id' AND app.current_correlation_id() IS NOT NULL THEN
    p := p || jsonb_build_object('correlation_id', app.current_correlation_id());
  END IF;
  NEW := jsonb_populate_record(NEW, p);
  RETURN NEW;
END $$;

-- ───────────── Trigger: entity_history (Niveau 2) ─────────────
-- TG_ARGV = secret columns, never copied into history.
CREATE OR REPLACE FUNCTION app.tg_entity_history() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  meta text[] := ARRAY['updated_at', 'updated_by', 'version_number', 'correlation_id'];
  secrets text[] := coalesce(TG_ARGV, '{}'::text[]);
  old_j jsonb; new_j jsonb; row_j jsonb;
  op text; ver int; changed text[]; tid uuid;
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN old_j := to_jsonb(OLD) - secrets; END IF;
  IF TG_OP IN ('UPDATE', 'INSERT') THEN new_j := to_jsonb(NEW) - secrets; END IF;
  IF TG_OP = 'INSERT' THEN
    op := 'INSERT'; ver := (new_j->>'version_number')::int;
  ELSIF TG_OP = 'UPDATE' THEN
    IF new_j->'version_number' = old_j->'version_number' THEN RETURN NULL; END IF;
    ver := (new_j->>'version_number')::int;
    op := CASE
      WHEN old_j->>'deleted_at' IS NULL AND new_j->>'deleted_at' IS NOT NULL THEN 'SOFT_DELETE'
      WHEN old_j->>'deleted_at' IS NOT NULL AND new_j->>'deleted_at' IS NULL THEN 'RESTORE'
      ELSE 'UPDATE' END;
    SELECT array_agg(k ORDER BY k) INTO changed
      FROM jsonb_object_keys(new_j) k
     WHERE NOT (k = ANY (meta)) AND new_j->k IS DISTINCT FROM old_j->k;
  ELSE
    op := 'DELETE'; ver := (old_j->>'version_number')::int + 1;
  END IF;
  row_j := coalesce(new_j, old_j);
  tid := CASE WHEN TG_TABLE_NAME = 'tenants' THEN (row_j->>'id')::uuid ELSE (row_j->>'tenant_id')::uuid END;
  INSERT INTO public.entity_history (tenant_id, entity_type, entity_id, version_number, operation,
      previous_data, current_data, changed_fields, changed_by, actor_type, change_reason, correlation_id)
  VALUES (tid, TG_TABLE_NAME, (row_j->>'id')::uuid, ver, op, old_j, new_j, changed,
      app.current_user_id(), app.current_actor_type(), app.change_reason(),
      coalesce((row_j->>'correlation_id')::uuid, app.current_correlation_id()));
  RETURN NULL;
END $$;

-- ───────────── Trigger: append-only journals ─────────────
-- Mutation is possible only inside app.correct_log_entry / app.purge_expired (SECURITY DEFINER),
-- which set app.allow_log_mutation for the current transaction. In production Django logs in as the
-- dedicated LOGIN role `growth_backend` (member of app_backend only), which is never allowed here.
CREATE OR REPLACE FUNCTION app.tg_append_only() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  IF coalesce(current_setting('app.allow_log_mutation', true), '') = 'on'
     AND session_user::text <> 'growth_backend' THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  RAISE EXCEPTION 'append-only journal %: % is forbidden (use app.correct_log_entry)', TG_TABLE_NAME, TG_OP
    USING ERRCODE = '42501';
END $$;

-- ───────────── SQL-side audit helper (used by DB functions; Django writes its own events) ─────────────
CREATE OR REPLACE FUNCTION app.log_audit_event(
  p_tenant uuid, p_action text, p_module text, p_entity_type text, p_entity_id uuid,
  p_description text, p_before jsonb DEFAULT NULL, p_after jsonb DEFAULT NULL,
  p_source text DEFAULT 'sql', p_status text DEFAULT 'success'
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_id uuid;
BEGIN
  INSERT INTO public.audit_events (tenant_id, actor_user_id, actor_type, action, module, entity_type, entity_id,
      description, before_data, after_data, source, status, request_id, correlation_id)
  VALUES (p_tenant, app.current_user_id(),
      CASE WHEN app.current_actor_type() IN ('user','pilot','system','celery','agent','webhook','anonymous')
           THEN app.current_actor_type() ELSE 'system' END,
      p_action, p_module, p_entity_type, p_entity_id, p_description, p_before, p_after, p_source, p_status,
      app.current_request_id(), app.current_correlation_id())
  RETURNING id INTO v_id;
  RETURN v_id;
END $$;
REVOKE EXECUTE ON FUNCTION app.log_audit_event(uuid, text, text, text, uuid, text, jsonb, jsonb, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION app.log_audit_event(uuid, text, text, text, uuid, text, jsonb, jsonb, text, text) TO app_backend;

-- ───────────── Controlled administrative correction of a journal row (itself audited) ─────────────
CREATE OR REPLACE FUNCTION app.correct_log_entry(p_table text, p_id uuid, p_patch jsonb, p_reason text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_before jsonb; v_after jsonb; v_set text;
BEGIN
  IF NOT app.current_is_platform() THEN
    RAISE EXCEPTION 'platform scope required' USING ERRCODE = '42501';
  END IF;
  IF coalesce(btrim(p_reason), '') = '' THEN RAISE EXCEPTION 'reason required'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_01_append_only'
                  AND tgrelid = to_regclass('public.' || p_table)) THEN
    RAISE EXCEPTION '% is not an append-only journal', p_table;
  END IF;
  IF p_patch ?| ARRAY['id', 'tenant_id', 'created_at'] THEN RAISE EXCEPTION 'identity columns cannot be corrected'; END IF;
  EXECUTE format('SELECT to_jsonb(t) FROM public.%I t WHERE id = $1', p_table) INTO v_before USING p_id;
  IF v_before IS NULL THEN RAISE EXCEPTION 'row not found'; END IF;
  SELECT string_agg(format('%I = (jsonb_populate_record(NULL::public.%I, $2)).%I', k, p_table, k), ', ')
    INTO v_set FROM jsonb_object_keys(p_patch) k;
  PERFORM set_config('app.allow_log_mutation', 'on', true);
  EXECUTE format('UPDATE public.%I SET %s WHERE id = $1', p_table, v_set) USING p_id, p_patch;
  PERFORM set_config('app.allow_log_mutation', '', true);
  EXECUTE format('SELECT to_jsonb(t) FROM public.%I t WHERE id = $1', p_table) INTO v_after USING p_id;
  INSERT INTO public.audit_log_corrections (tenant_id, table_name, row_id, before_data, after_data, reason, corrected_by, correlation_id)
  VALUES ((v_before->>'tenant_id')::uuid, p_table, p_id, v_before, v_after, p_reason, app.current_user_id(), app.current_correlation_id());
  PERFORM app.log_audit_event((v_before->>'tenant_id')::uuid, 'journal.corrected', 'audit', p_table, p_id,
                              'Administrative journal correction: ' || p_reason, v_before, v_after, 'admin');
END $$;
REVOKE EXECUTE ON FUNCTION app.correct_log_entry(text, uuid, jsonb, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION app.correct_log_entry(text, uuid, jsonb, text) TO app_backend;

-- ───────────── Retention purge (only within an explicit, active retention policy) ─────────────
CREATE OR REPLACE FUNCTION app.purge_expired(p_table text, p_tenant uuid DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_days int; v_rule text; v_count bigint; v_cutoff timestamptz;
BEGIN
  IF NOT app.current_is_platform() THEN RAISE EXCEPTION 'platform scope required' USING ERRCODE = '42501'; END IF;
  SELECT retention_days, deletion_rule INTO v_days, v_rule
    FROM public.data_retention_policies
   WHERE data_category = p_table AND is_active AND deleted_at IS NULL
     AND (tenant_id = p_tenant OR tenant_id IS NULL)
   ORDER BY tenant_id NULLS LAST LIMIT 1;
  IF v_days IS NULL OR v_rule <> 'delete' THEN
    RETURN 0;  -- no explicit policy → never delete
  END IF;
  v_cutoff := now() - make_interval(days => v_days);
  PERFORM set_config('app.allow_log_mutation', 'on', true);
  EXECUTE format('DELETE FROM public.%I WHERE created_at < $1 AND ($2::uuid IS NULL OR tenant_id = $2)', p_table)
    USING v_cutoff, p_tenant;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  PERFORM set_config('app.allow_log_mutation', '', true);
  PERFORM app.log_audit_event(p_tenant, 'retention.purged', 'audit', p_table, NULL,
    format('Purged %s rows older than %s days', v_count, v_days), NULL,
    jsonb_build_object('rows', v_count, 'cutoff', v_cutoff), 'system');
  RETURN v_count;
END $$;
REVOKE EXECUTE ON FUNCTION app.purge_expired(text, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION app.purge_expired(text, uuid) TO app_backend;

-- ───────────── Monthly partitions for high-volume journals ─────────────
CREATE OR REPLACE FUNCTION app.ensure_monthly_partitions(p_table text, p_months_ahead int DEFAULT 3)
RETURNS int LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  m date; n int := 0; part text;
BEGIN
  FOR i IN -1..p_months_ahead LOOP
    m := (date_trunc('month', now()) + make_interval(months => i))::date;
    part := format('%s_%s', p_table, to_char(m, 'YYYY_MM'));
    IF to_regclass('public.' || part) IS NULL THEN
      EXECUTE format('CREATE TABLE public.%I PARTITION OF public.%I FOR VALUES FROM (%L) TO (%L)',
                     part, p_table, m, (m + interval '1 month')::date);
      -- partitions are reachable directly through the Data API: lock them down like the parent
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', part);
      EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', part);
      n := n + 1;
    END IF;
  END LOOP;
  RETURN n;
END $$;
REVOKE EXECUTE ON FUNCTION app.ensure_monthly_partitions(text, int) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION app.ensure_monthly_partitions(text, int) TO app_backend;
