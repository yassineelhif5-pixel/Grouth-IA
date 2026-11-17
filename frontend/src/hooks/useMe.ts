import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { api } from "@/services/api";
import { useSessionStore } from "@/stores/session";
import type { Me, TenantSummary } from "@/types/api";

export function useMe() {
  const session = useSessionStore((s) => s.session);
  return useQuery({ queryKey: ["me", session?.user.id], queryFn: () => api<Me>("/me"), enabled: !!session });
}

/** Current tenant comes from the URL (/t/:tenantId/...) and must belong to /me (server-verified). */
export function useTenant(): { tenantId: string; tenant: TenantSummary | undefined; can: (perm: string) => boolean; hasModule: (m: string) => boolean } {
  const { tenantId = "" } = useParams();
  const { data } = useMe();
  const tenant = data?.tenants.find((t) => t.id === tenantId);
  return {
    tenantId,
    tenant,
    can: (perm) => !!tenant?.permissions?.includes(perm),
    hasModule: (m) => !!tenant?.modules?.includes(m),
  };
}
