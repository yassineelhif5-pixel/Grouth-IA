import {
  IconActivityHeartbeat, IconAlertTriangle, IconArrowBack, IconBuildingSkyscraper, IconChartBar, IconGauge, IconHistory, IconListDetails,
  IconRobot, IconSitemap, IconTicket,
} from "@tabler/icons-react";
import { useTranslation } from "react-i18next";

import { Shell } from "./Shell";

export function PilotLayout() {
  const { t } = useTranslation();
  const i = (C: typeof IconGauge) => <C size={18} stroke={1.6} />;
  return (
    <Shell nav={[
      { group: "Plateforme", to: "/pilot/overview", label: t("nav.dashboard"), icon: i(IconGauge) },
      { group: "Plateforme", to: "/pilot/global", label: "Vue globale", icon: i(IconSitemap) },
      { group: "Clients", to: "/pilot/tenants", label: t("nav.tenants"), icon: i(IconBuildingSkyscraper) },
      { group: "Clients", to: "/pilot/plans", label: t("nav.plans"), icon: i(IconListDetails) },
      { group: "Clients", to: "/pilot/usage", label: t("nav.usage"), icon: i(IconChartBar) },
      { group: "Exploitation", to: "/pilot/ai", label: "Fournisseurs IA", icon: i(IconRobot) },
      { group: "Exploitation", to: "/pilot/health", label: t("nav.health"), icon: i(IconActivityHeartbeat) },
      { group: "Exploitation", to: "/pilot/incidents", label: t("nav.incidents"), icon: i(IconTicket) },
      { group: "Exploitation", to: "/pilot/errors", label: t("nav.errors"), icon: i(IconAlertTriangle) },
      { group: "Exploitation", to: "/pilot/history", label: t("nav.logs"), icon: i(IconHistory) },
      { group: "", to: "/", label: "Espace tenant", icon: i(IconArrowBack) },
    ]} />
  );
}
