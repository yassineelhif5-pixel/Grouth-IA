import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "./global.css";

import { MantineProvider } from "@mantine/core";
import { Notifications, notifications } from "@mantine/notifications";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useEffect } from "react";

import { ApiError } from "@/services/api";
import { supabase } from "@/services/supabase";
import { useSessionStore } from "@/stores/session";

import { theme } from "./theme";


const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2 } },
  mutationCache: new MutationCache({
    onError: (e) =>
      notifications.show({
        color: "red",
        title: e instanceof ApiError ? e.code : "Error",
        message: e instanceof ApiError && e.requestId ? `${e.message} (ref ${e.requestId.slice(0, 8)})` : e.message,
      }),
  }),
});

function SessionSync() {
  const setSession = useSessionStore((s) => s.setSession);
  useEffect(() => {
    void supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_evt, session) => {
      setSession(session);
      void queryClient.invalidateQueries();
    });
    return () => data.subscription.unsubscribe();
  }, [setSession]);
  return null;
}

export function Providers({ children }: { children: ReactNode }) {
  return (
    <MantineProvider theme={theme} defaultColorScheme="dark">
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>
        <SessionSync />
        {children}
      </QueryClientProvider>
    </MantineProvider>
  );
}
