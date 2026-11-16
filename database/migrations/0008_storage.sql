-- Growth IA — Migration 0008 — private Supabase Storage buckets & tenant-scoped object policies
-- Object path convention: <tenant_id>/<module>/<...>. Skipped when the storage schema is absent (local tests).
DO $$
BEGIN
  IF to_regclass('storage.buckets') IS NULL THEN
    RAISE NOTICE 'storage schema not present: skipping';
    RETURN;
  END IF;
  INSERT INTO storage.buckets (id, name, public, file_size_limit)
  VALUES ('tenant-files', 'tenant-files', false, 52428800),
         ('email-attachments', 'email-attachments', false, 26214400),
         ('exports', 'exports', false, 104857600),
         ('reports', 'reports', false, 52428800)
  ON CONFLICT (id) DO NOTHING;

  DROP POLICY IF EXISTS growth_tenant_read ON storage.objects;
  CREATE POLICY growth_tenant_read ON storage.objects FOR SELECT TO authenticated
    USING (bucket_id IN ('tenant-files', 'email-attachments', 'reports')
           AND (storage.foldername(name))[1] ~* '^[0-9a-f-]{36}$'
           AND app.is_tenant_member(((storage.foldername(name))[1])::uuid));
  DROP POLICY IF EXISTS growth_exports_read ON storage.objects;
  CREATE POLICY growth_exports_read ON storage.objects FOR SELECT TO authenticated
    USING (bucket_id = 'exports'
           AND (storage.foldername(name))[1] ~* '^[0-9a-f-]{36}$'
           AND app.is_tenant_admin(((storage.foldername(name))[1])::uuid));
  -- Writes go through Django (service role) which validates tenant & permissions and logs record_access_logs.
END $$;
