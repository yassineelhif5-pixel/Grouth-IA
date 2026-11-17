-- Growth IA — login by e-mail OR username. Additive and idempotent.
-- Supabase Auth only knows e-mails: the backend resolves a username to its e-mail through
-- app.login_email() (SECURITY DEFINER, callable by app_backend only) and never returns the e-mail to the client.

ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS username text;

ALTER TABLE public.user_profiles DROP CONSTRAINT IF EXISTS user_profiles_username_format,
  ADD CONSTRAINT user_profiles_username_format CHECK (username IS NULL OR username ~ '^[a-z0-9][a-z0-9._-]{2,29}$');

CREATE UNIQUE INDEX IF NOT EXISTS user_profiles_username_key ON public.user_profiles (username) WHERE username IS NOT NULL;

-- Canonical form: trimmed, lowercase, 3–30 chars [a-z0-9._-], starting with a letter or digit. NULL when invalid.
CREATE OR REPLACE FUNCTION app.normalize_username(p text) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path = '' AS $$
  SELECT CASE WHEN lower(btrim(p)) ~ '^[a-z0-9][a-z0-9._-]{2,29}$' THEN lower(btrim(p)) END
$$;

-- Taken by an existing profile, or reserved at sign-up (auth metadata) by another account.
CREATE OR REPLACE FUNCTION app.username_taken(p text, p_except uuid DEFAULT NULL) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT EXISTS (SELECT 1 FROM public.user_profiles WHERE username = app.normalize_username(p)
                  AND id IS DISTINCT FROM p_except)
      OR EXISTS (SELECT 1 FROM auth.users u WHERE lower(btrim(u.raw_user_meta_data ->> 'username')) = app.normalize_username(p)
                  AND u.id IS DISTINCT FROM p_except)
$$;

-- E-mail to authenticate with. An identifier containing '@' is an e-mail; otherwise it is a username
-- (active profile first, then a confirmed account that reserved it at sign-up and has no profile yet).
CREATE OR REPLACE FUNCTION app.login_email(p_identifier text) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_user text := app.normalize_username(p_identifier); v_email text; v_count int;
BEGIN
  IF position('@' IN coalesce(p_identifier, '')) > 0 THEN
    RETURN lower(btrim(p_identifier));
  END IF;
  IF v_user IS NULL THEN RETURN NULL; END IF;
  SELECT email INTO v_email FROM public.user_profiles WHERE username = v_user AND status = 'active';
  IF v_email IS NOT NULL THEN RETURN v_email; END IF;
  SELECT count(*), min(u.email) INTO v_count, v_email FROM auth.users u
   WHERE lower(btrim(u.raw_user_meta_data ->> 'username')) = v_user AND u.email_confirmed_at IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM public.user_profiles p WHERE p.id = u.id);
  RETURN CASE WHEN v_count = 1 THEN v_email END;
END $$;

-- A new profile takes the username chosen at sign-up (Supabase user_metadata) when valid and still free.
CREATE OR REPLACE FUNCTION app.tg_profile_username() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v text;
BEGIN
  IF NEW.username IS NULL THEN
    SELECT app.normalize_username(u.raw_user_meta_data ->> 'username') INTO v FROM auth.users u WHERE u.id = NEW.id;
    IF v IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.user_profiles WHERE username = v) THEN
      NEW.username := v;
    END IF;
  ELSE
    NEW.username := app.normalize_username(NEW.username);
    IF NEW.username IS NULL THEN
      RAISE EXCEPTION 'invalid username' USING ERRCODE = '23514', CONSTRAINT = 'user_profiles_username_format';
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS a_profile_username ON public.user_profiles;
CREATE TRIGGER a_profile_username BEFORE INSERT OR UPDATE OF username ON public.user_profiles
  FOR EACH ROW EXECUTE FUNCTION app.tg_profile_username();

REVOKE ALL ON FUNCTION app.login_email(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.username_taken(text, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION app.tg_profile_username() FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    EXECUTE 'REVOKE ALL ON FUNCTION app.login_email(text) FROM anon, authenticated';
    EXECUTE 'REVOKE ALL ON FUNCTION app.username_taken(text, uuid) FROM anon, authenticated';
  END IF;
END $$;
GRANT EXECUTE ON FUNCTION app.login_email(text) TO app_backend;
GRANT EXECUTE ON FUNCTION app.username_taken(text, uuid) TO app_backend;
GRANT EXECUTE ON FUNCTION app.normalize_username(text) TO app_backend;
