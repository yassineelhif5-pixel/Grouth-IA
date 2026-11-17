import type { Session } from "@supabase/supabase-js";
import { create } from "zustand";

/** UI session state only. Durable data (tenants, history, settings) always comes from the API. */
interface SessionState {
  session: Session | null;
  ready: boolean;
  setSession: (s: Session | null) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  session: null,
  ready: false,
  setSession: (session) => set({ session, ready: true }),
}));
