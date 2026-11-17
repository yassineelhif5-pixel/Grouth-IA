-- Growth IA — login by e-mail or username: format, uniqueness, sign-up reservation, lookup, privileges. Rolled back.
\set ON_ERROR_STOP 1
BEGIN;
SET LOCAL client_min_messages = warning;
CREATE FUNCTION pg_temp.ok(cond boolean, msg text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN IF cond IS NOT TRUE THEN RAISE EXCEPTION 'FAIL: %', msg; END IF; RAISE NOTICE 'ok - %', msg; END $$;
SET LOCAL client_min_messages = notice;

DO $$ DECLARE a uuid := gen_random_uuid(); b uuid := gen_random_uuid(); c uuid := gen_random_uuid(); BEGIN
  INSERT INTO auth.users (id, email, email_confirmed_at, raw_user_meta_data) VALUES
    (a, 'un-a-' || a || '@example.test', now(), '{"username": " Alice.Martin "}'),
    (b, 'un-b-' || b || '@example.test', now(), '{"username": "alice.martin"}'),
    (c, 'un-c-' || c || '@example.test', now(), '{"username": "carole"}');
  PERFORM set_config('t.a', a::text, true); PERFORM set_config('t.b', b::text, true); PERFORM set_config('t.c', c::text, true);
END $$;

SELECT pg_temp.ok(app.normalize_username('  Jean-Luc_42 ') = 'jean-luc_42', 'username normalised (trim + lowercase)');
SELECT pg_temp.ok(app.normalize_username('ab') IS NULL AND app.normalize_username('a b c') IS NULL
                  AND app.normalize_username('x@y.fr') IS NULL AND app.normalize_username('-abc') IS NULL, 'invalid usernames rejected');

-- confirmed account without profile yet: username reserved at sign-up is usable only if unique
SELECT pg_temp.ok(app.login_email('carole') = 'un-c-' || current_setting('t.c') || '@example.test', 'sign-up username resolves before profile creation');
SELECT pg_temp.ok(app.login_email('alice.martin') IS NULL, 'ambiguous sign-up username resolves to nothing');

-- profile creation takes the sign-up username; the second claimant does not get it
INSERT INTO public.user_profiles (id, email) SELECT id, email FROM auth.users WHERE id = current_setting('t.a')::uuid;
INSERT INTO public.user_profiles (id, email) SELECT id, email FROM auth.users WHERE id = current_setting('t.b')::uuid;
SELECT pg_temp.ok((SELECT username FROM public.user_profiles WHERE id = current_setting('t.a')::uuid) = 'alice.martin', 'profile inherits sign-up username');
SELECT pg_temp.ok((SELECT username FROM public.user_profiles WHERE id = current_setting('t.b')::uuid) IS NULL, 'taken username not assigned twice');
SELECT pg_temp.ok(app.login_email('ALICE.MARTIN') = 'un-a-' || current_setting('t.a') || '@example.test', 'login by username (case-insensitive)');
SELECT pg_temp.ok(app.login_email(' Someone@Example.TEST ') = 'someone@example.test', 'identifier with @ treated as e-mail');
SELECT pg_temp.ok(app.login_email('nobody-here') IS NULL, 'unknown username resolves to nothing');
SELECT pg_temp.ok(app.username_taken('Alice.Martin') AND NOT app.username_taken('free-name-xyz'), 'availability check');

DO $$ BEGIN
  BEGIN
    UPDATE public.user_profiles SET username = 'Alice.Martin' WHERE id = current_setting('t.b')::uuid;
    RAISE EXCEPTION 'FAIL: duplicate username accepted';
  EXCEPTION WHEN unique_violation THEN RAISE NOTICE 'ok - duplicate username refused (case-insensitive)';
  END;
  BEGIN
    UPDATE public.user_profiles SET username = 'a b' WHERE id = current_setting('t.b')::uuid;
    RAISE EXCEPTION 'FAIL: invalid username accepted';
  EXCEPTION WHEN check_violation THEN RAISE NOTICE 'ok - invalid username refused';
  END;
END $$;
UPDATE public.user_profiles SET username = 'Bob_2026' WHERE id = current_setting('t.b')::uuid;
SELECT pg_temp.ok((SELECT username FROM public.user_profiles WHERE id = current_setting('t.b')::uuid) = 'bob_2026', 'username change stored normalised');
SELECT pg_temp.ok(EXISTS (SELECT 1 FROM public.entity_history WHERE entity_id = current_setting('t.b')::uuid AND entity_type = 'user_profiles'), 'username change versioned in entity_history');

UPDATE public.user_profiles SET status = 'suspended' WHERE id = current_setting('t.b')::uuid;
SELECT pg_temp.ok(app.login_email('bob_2026') IS NULL, 'suspended profile cannot log in by username');

-- privileges: only the backend role resolves usernames
SELECT pg_temp.ok(has_function_privilege('app_backend', 'app.login_email(text)', 'EXECUTE'), 'app_backend may resolve usernames');
SELECT pg_temp.ok(NOT has_function_privilege('authenticated', 'app.login_email(text)', 'EXECUTE')
                  AND NOT has_function_privilege('anon', 'app.login_email(text)', 'EXECUTE'), 'anon/authenticated cannot resolve usernames');

DO $$ BEGIN RAISE NOTICE 'ALL USERNAME SQL TESTS PASSED'; END $$;
ROLLBACK;
