import { Alert, Anchor } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api } from "@/services/api";

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
  return <Shell nav={items.filter((i) => i.show)} header={<TenantSwitcher current={tenantId} />} banner={<TrialBanner tenantId={tenantId} />} />;
}

/** Trial / subscription banner: countdown during the free trial, read-only notice once it is over. */
function TrialBanner({ tenantId }: { tenantId: string }) {
  const q = useQuery({
    queryKey: ["license", tenantId], retry: false,
    queryFn: () => api<{ subscription: { status: string; trial_ends_at: string | null; plan_name: string } | null }>("/license", { tenantId }),
  });
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const id = window.setInterval(() => setNow(Date.now()), 60_000); return () => window.clearInterval(id); }, []);
  const s = q.data?.subscription;
  if (!s) return null;
  const link = <Anchor component={Link} to={`/t/${tenantId}/subscription`} fw={600}>Choisir mon abonnement</Anchor>;
  const end = s.trial_ends_at ? new Date(s.trial_ends_at) : null;
  const over = ["expired", "suspended", "cancelled"].includes(s.status) || (s.status === "trialing" && end !== null && end.getTime() < now);
  if (over) {
    return <Alert color="red" mb="md" title="Votre période d'essai est terminée">
      L'espace est en lecture seule jusqu'à la souscription d'une offre (Starter 20 €, Pro 50 € ou Professionnelle 200 € TTC / mois). {link}
    </Alert>;
  }
  if (s.status === "past_due") return <Alert color="orange" mb="md">Le dernier paiement a échoué : mettez à jour votre moyen de paiement. {link}</Alert>;
  if (s.status === "trialing" && end) {
    const hours = Math.max(0, Math.round((end.getTime() - now) / 3_600_000));
    return <Alert color="blue" mb="md">
      Essai gratuit : il reste {hours >= 24 ? `${Math.floor(hours / 24)} j ${hours % 24} h` : `${hours} h`} (fin le {end.toLocaleString("fr-FR")}). {link}
    </Alert>;
  }
  return null;
}
