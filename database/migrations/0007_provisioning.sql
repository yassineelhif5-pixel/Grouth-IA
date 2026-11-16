-- Growth IA — Migration 0007 — transactional DEMO provisioning & licence jobs

-- Called by Django (role app_backend) inside the signup transaction, after e-mail verification.
CREATE OR REPLACE FUNCTION app.provision_demo_tenant(p_user_id uuid, p_tenant_name text, p_slug text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_email text; v_confirmed timestamptz;
  v_tenant uuid := gen_random_uuid();
  v_member uuid; v_plan record; v_sub uuid; v_trial uuid; v_expires timestamptz;
BEGIN
  SELECT email, email_confirmed_at INTO v_email, v_confirmed FROM auth.users WHERE id = p_user_id;
  IF v_email IS NULL THEN RAISE EXCEPTION 'unknown user' USING ERRCODE = 'P0002'; END IF;
  IF v_confirmed IS NULL THEN RAISE EXCEPTION 'email not verified' USING ERRCODE = '42501'; END IF;

  -- One automatic owner-tenant per DEMO user, even under concurrent requests.
  PERFORM pg_advisory_xact_lock(hashtext('demo_provision:' || p_user_id::text));
  IF EXISTS (SELECT 1 FROM public.tenant_owner_registry WHERE user_id = p_user_id AND source = 'demo_signup') THEN
    RAISE EXCEPTION 'demo tenant already provisioned for this user' USING ERRCODE = '23505';
  END IF;

  PERFORM set_config('app.tenant_id', v_tenant::text, true);
  PERFORM set_config('app.user_id', p_user_id::text, true);
  IF coalesce(current_setting('app.correlation_id', true), '') = '' THEN
    PERFORM set_config('app.correlation_id', gen_random_uuid()::text, true);
  END IF;

  INSERT INTO public.user_profiles (id, email, email_verified_at)
  VALUES (p_user_id, v_email, v_confirmed) ON CONFLICT (id) DO NOTHING;

  INSERT INTO public.tenants (id, name, slug, status, owner_user_id, is_demo)
  VALUES (v_tenant, p_tenant_name, p_slug, 'active', p_user_id, true);
  INSERT INTO public.tenant_owner_registry (tenant_id, user_id, source) VALUES (v_tenant, p_user_id, 'demo_signup');

  INSERT INTO public.tenant_members (tenant_id, user_id, status) VALUES (v_tenant, p_user_id, 'active')
  RETURNING id INTO v_member;
  INSERT INTO public.tenant_memberships (tenant_id, member_id, role_id, granted_reason)
  SELECT v_tenant, v_member, r.id, 'demo signup owner' FROM public.tenant_roles r
   WHERE r.tenant_id IS NULL AND r.code = 'tenant_owner';

  SELECT * INTO v_plan FROM public.subscription_plans WHERE code = 'DEMO' AND is_active;
  IF v_plan.id IS NULL THEN RAISE EXCEPTION 'DEMO plan not configured'; END IF;
  v_expires := now() + make_interval(hours => coalesce(v_plan.trial_duration_hours, 72));

  INSERT INTO public.tenant_subscriptions (tenant_id, plan_id, status, current_period_start, current_period_end, trial_ends_at)
  VALUES (v_tenant, v_plan.id, 'trialing', now(), v_expires, v_expires) RETURNING id INTO v_sub;
  INSERT INTO public.trial_activations (tenant_id, plan_id, user_id, expires_at)
  VALUES (v_tenant, v_plan.id, p_user_id, v_expires) RETURNING id INTO v_trial;
  INSERT INTO public.tenant_subscription_history (tenant_id, subscription_id, event_type, to_plan_id, actor_user_id, reason)
  VALUES (v_tenant, v_sub, 'created', v_plan.id, p_user_id, 'DEMO signup');

  INSERT INTO public.tenant_license_quotas (tenant_id, quota_code, limit_value, period, period_start, source)
  SELECT v_tenant, q.quota_code, q.limit_value, q.period, now(), 'trial'
    FROM public.subscription_plan_quotas q WHERE q.plan_id = v_plan.id;
  INSERT INTO public.tenant_license_feature_access (tenant_id, feature_id, enabled, source)
  SELECT v_tenant, f.feature_id, f.enabled, 'trial' FROM public.subscription_plan_features f WHERE f.plan_id = v_plan.id;
  INSERT INTO public.tenant_module_authorizations (tenant_id, module_id, status, reason)
  SELECT DISTINCT v_tenant, pf.module_id, 'enabled', 'plan DEMO'
    FROM public.subscription_plan_features f JOIN public.platform_module_features pf ON pf.id = f.feature_id
   WHERE f.plan_id = v_plan.id;

  PERFORM app.log_audit_event(v_tenant, 'tenant.provisioned', 'tenants', 'tenants', v_tenant,
    'DEMO tenant created by signup', NULL, jsonb_build_object('name', p_tenant_name, 'slug', p_slug), 'api');
  PERFORM app.log_audit_event(v_tenant, 'subscription.trial_started', 'licensing', 'tenant_subscriptions', v_sub,
    'DEMO trial activated (72h)', NULL, jsonb_build_object('expires_at', v_expires), 'api');
  INSERT INTO public.activity_events (tenant_id, user_id, event_type, module, entity_type, entity_id, description)
  VALUES (v_tenant, p_user_id, 'tenant.created', 'tenants', 'tenants', v_tenant, 'Espace DEMO créé');
  RETURN v_tenant;
END $$;
REVOKE EXECUTE ON FUNCTION app.provision_demo_tenant(uuid, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION app.provision_demo_tenant(uuid, text, text) TO app_backend;

-- Celery licence job: expire finished trials (platform scope). Returns the number of expired trials.
CREATE OR REPLACE FUNCTION app.expire_trials() RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE r record; n int := 0;
BEGIN
  IF NOT app.current_is_platform() THEN RAISE EXCEPTION 'platform scope required' USING ERRCODE = '42501'; END IF;
  FOR r IN SELECT s.id, s.tenant_id, s.plan_id FROM public.tenant_subscriptions s
            WHERE s.status = 'trialing' AND s.trial_ends_at < now() AND s.deleted_at IS NULL FOR UPDATE LOOP
    UPDATE public.tenant_subscriptions SET status = 'expired' WHERE id = r.id;
    UPDATE public.trial_activations SET status = 'expired'
     WHERE tenant_id = r.tenant_id AND status = 'active';
    INSERT INTO public.tenant_subscription_history (tenant_id, subscription_id, event_type, from_plan_id, reason)
    VALUES (r.tenant_id, r.id, 'expired', r.plan_id, 'trial period ended');
    PERFORM app.log_audit_event(r.tenant_id, 'subscription.trial_expired', 'licensing', 'tenant_subscriptions', r.id,
      'Trial expired automatically', NULL, NULL, 'celery');
    n := n + 1;
  END LOOP;
  RETURN n;
END $$;
REVOKE EXECUTE ON FUNCTION app.expire_trials() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION app.expire_trials() TO app_backend;

-- Unique DEMO ownership (partial): a user may own other tenants created by the PILOTE.
CREATE UNIQUE INDEX IF NOT EXISTS ux_tenant_owner_registry_demo
  ON public.tenant_owner_registry (user_id) WHERE source = 'demo_signup';
