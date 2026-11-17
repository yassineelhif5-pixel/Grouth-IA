import { useTranslation } from "react-i18next";

import { useMe, useTenant } from "@/hooks/useMe";

import { Shell, TenantSwitcher, type NavItem } from "./Shell";

/** Only modules authorized by the licence AND permitted to the user are shown (the API enforces the same rules). */
export function TenantLayout() {
  const { t } = useTranslation();
  const { tenantId, can, hasModule } = useTenant();
  const { data } = useMe();
  const b = `/t/${tenantId}`;
  const m = (mod: string, perm: string) => hasModule(mod) && can(perm);
  const items: (NavItem & { show: boolean })[] = [
    { to: `${b}/dashboard`, label: t("nav.dashboard"), show: can("reporting.read") },
    { to: `${b}/products`, label: t("nav.products"), show: m("products", "products.read") },
    { to: `${b}/websites`, label: t("nav.websites"), show: m("websites", "websites.read") },
    { to: `${b}/seo`, label: "SEO Intelligence", show: m("seo", "seo.read") },
    { to: `${b}/geo`, label: "GEO Intelligence", show: m("geo", "geo.read") },
    { to: `${b}/content`, label: "Content Studio", show: m("content", "content.read") },
    { to: `${b}/pages`, label: "Page Builder", show: m("pages", "pages.read") },
    { to: `${b}/social`, label: "Social Media", show: m("social", "social.read") },
    { to: `${b}/video`, label: "Video Studio", show: m("video", "video.read") },
    { to: `${b}/opportunities`, label: "Opportunity Hunter", show: m("opportunities", "opportunities.read") },
    { to: `${b}/prospects`, label: "Smart Prospect", show: m("prospects", "prospects.read") },
    { to: `${b}/email`, label: "Email Center", show: m("email_center", "email.read") },
    { to: `${b}/whatsapp`, label: "WhatsApp Center", show: m("whatsapp", "whatsapp.read") },
    { to: `${b}/crm`, label: "CRM", show: m("crm", "crm.read") },
    { to: `${b}/campaigns`, label: "Campaigns", show: m("prospects", "campaigns.read") },
    { to: `${b}/scheduler`, label: t("nav.scheduler"), show: m("scheduler", "scheduler.read") },
    { to: `${b}/workflows`, label: "Workflows", show: m("workflows", "workflows.read") },
    { to: `${b}/intelligence`, label: "Growth Intelligence", show: m("intelligence", "intelligence.read") },
    { to: `${b}/thor`, label: "THOR", show: m("thor", "thor.use") },
    { to: `${b}/approvals`, label: "Validations", show: can("approvals.decide") },
    { to: `${b}/reporting`, label: t("nav.reporting"), show: can("reporting.read") },
    { to: `${b}/history`, label: t("nav.history"), show: can("history.read") },
    { to: `${b}/members`, label: "Team", show: can("members.read") },
    { to: `${b}/invitations`, label: t("nav.invitations"), show: can("invitations.manage") },
    { to: `${b}/connectors`, label: t("nav.connectors"), show: can("connectors.read") },
    { to: `${b}/subscription`, label: t("nav.subscription"), show: can("licenses.read") },
    { to: `${b}/settings`, label: t("nav.settings"), show: true },
    { to: "/pilot", label: t("nav.pilot"), show: !!data?.user.is_pilot },
  ];
  return <Shell nav={items.filter((i) => i.show)} header={<TenantSwitcher current={tenantId} />} />;
}
