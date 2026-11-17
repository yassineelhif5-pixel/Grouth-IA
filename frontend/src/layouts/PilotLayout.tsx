import { useTranslation } from "react-i18next";

import { Shell } from "./Shell";

export function PilotLayout() {
  const { t } = useTranslation();
  return (
    <Shell nav={[
      { to: "/pilot/overview", label: t("nav.dashboard") },
      { to: "/pilot/tenants", label: t("nav.tenants") },
      { to: "/pilot/plans", label: t("nav.plans") },
      { to: "/pilot/usage", label: t("nav.usage") },
      { to: "/pilot/history", label: t("nav.logs") },
      { to: "/pilot/errors", label: t("nav.errors") },
      { to: "/pilot/health", label: t("nav.health") },
      { to: "/pilot/incidents", label: t("nav.incidents") },
      { to: "/pilot/ai", label: "Fournisseurs IA" },
      { to: "/pilot/global", label: "Vue globale" },
      { to: "/", label: "← Tenant" },
    ]} />
  );
}
