-- Growth IA — Migration 0010 — controlled read-state update on the append-only notifications journal
CREATE OR REPLACE FUNCTION app.mark_notifications_read(p_ids uuid[]) RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE n int;
BEGIN
  PERFORM set_config('app.allow_log_mutation', 'on', true);
  UPDATE public.notifications SET read_at = now()
   WHERE id = ANY (p_ids) AND user_id = app.current_user_id() AND read_at IS NULL;
  GET DIAGNOSTICS n = ROW_COUNT;
  PERFORM set_config('app.allow_log_mutation', '', true);
  RETURN n;
END $$;
REVOKE EXECUTE ON FUNCTION app.mark_notifications_read(uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION app.mark_notifications_read(uuid[]) TO app_backend;
