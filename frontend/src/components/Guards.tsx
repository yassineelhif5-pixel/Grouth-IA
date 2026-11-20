import { Center, Loader } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useMe, useTenant } from "@/hooks/useMe";
import { useSessionStore } from "@/stores/session";

export function FullLoader() {
  return (
    <Center h="60vh">
      <Loader />
    </Center>
  );
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, ready } = useSessionStore();
  const loc = useLocation();
  if (!ready) return <FullLoader />;
  if (!session) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return <>{children}</>;
}

/** PILOTE routes: platform role + MFA (aal2) unless disabled (PILOT_REQUIRE_MFA=false). The backend enforces the same rules. */
export function RequirePilot({ children }: { children: ReactNode }) {
  const { data, isLoading } = useMe();
  if (isLoading) return <FullLoader />;
  if (!data?.user.is_pilot) return <Navigate to="/" replace />;
  if (data.user.pilot_mfa_required !== false && data.user.aal !== "aal2") return <Navigate to="/mfa" replace />;
  return <>{children}</>;
}

export function RequireTenant({ children }: { children: ReactNode }) {
  const { isLoading } = useMe();
  const { tenant } = useTenant();
  if (isLoading) return <FullLoader />;
  if (!tenant) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export function RequirePermission({ perm, module, children }: { perm?: string; module?: string; children: ReactNode }) {
  const { can, hasModule } = useTenant();
  if ((perm && !can(perm)) || (module && !hasModule(module))) return <Navigate to=".." replace />;
  return <>{children}</>;
}
