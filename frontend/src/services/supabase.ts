import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;
if (!url || !anonKey) {
  // eslint-disable-next-line no-console
  console.error("VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are not configured");
}

/** Browser client: only the public anon key. All writes go through the Django API. */
export const supabase = createClient(url ?? "http://localhost", anonKey ?? "missing", {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});
