import { useTranslation } from "react-i18next";

import { useMe, useTenant } from "@/hooks/useMe";

import { Shell, TenantSwitcher, type NavItem } from "./Shell";

/** Only modules authorized by the licence and permitted to the user are shown. */
export function TenantLayout() {
  const { t } = useTranslation();
  const { tenantId, can, hasModule } = useTenant();
  const { data } = useMe();
  const base = `/t/${tenantId}`;
  const items: (NavItem & { show: boolean })[] = [
    { to: `${base}/dashboard`, label: t("nav.dashboard"), show: can("reporting.read") },
    { to: `${base}/products`, label: t("nav.products"), show: hasModule("products") && can("products.read") },
    { to: `${base}/websites`, label: t("nav.websites"), show: hasModule("websites") && can("websites.read") },
    { to: `${base}/scheduler`, label: t("nav.scheduler"), show: hasModule("scheduler") && can("scheduler.read") },
    { to: `${base}/connectors`, label: t("nav.connectors"), show: hasModule("connectors") && can("connectors.read") },
    { to: `${base}/members`, label: t("nav.members"), show: can("members.read") },
    { to: `${base}/invitations`, label: t("nav.invitations"), show: can("invitations.manage") },
    { to: `${base}/history`, label: t("nav.history"), show: can("history.read") },
    { to: `${base}/subscription`, label: t("nav.subscription"), show: can("licenses.read") },
    { to: `${base}/settings`, label: t("nav.settings"), show: true },
    { to: "/pilot", label: t("nav.pilot"), show: !!data?.user.is_pilot },
  ];
  return <Shell nav={items.filter((i) => i.show)} header={<TenantSwitcher current={tenantId} />} />;
}
