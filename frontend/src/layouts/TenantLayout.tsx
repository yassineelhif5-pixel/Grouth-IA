import { Alert, Anchor } from "@mantine/core";
import {
  IconAddressBook, IconBox, IconBrandWhatsapp, IconBulb, IconCalendarTime, IconChecklist, IconCreditCard, IconGauge, IconGitBranch,
  IconHistory, IconLayout, IconMail, IconMessageChatbot, IconPencil, IconPlugConnected, IconRadar, IconReportAnalytics, IconSearch,
  IconSend, IconSettings, IconShare, IconShieldLock, IconSparkles, IconStethoscope, IconTargetArrow, IconUsers, IconUserSearch, IconVideo,
  IconWorld, IconWorldSearch,
} from "@tabler/icons-react";
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
  const i = (C: typeof IconGauge) => <C size={18} stroke={1.6} />;
  const items: (NavItem & { show: boolean })[] = [
    { group: "Pilotage", to: `${b}/dashboard`, label: t("nav.dashboard"), icon: i(IconGauge), show: can("reporting.read") },
    { group: "Pilotage", to: `${b}/audit`, label: "Audit & roadmap", icon: i(IconStethoscope), show: m("seo", "seo.read") },
    { group: "Pilotage", to: `${b}/reporting`, label: t("nav.reporting"), icon: i(IconReportAnalytics), show: can("reporting.read") },
    { group: "Pilotage", to: `${b}/approvals`, label: "Validations", icon: i(IconChecklist), show: can("approvals.decide") },
    { group: "Visibilité", to: `${b}/visibility`, label: "Programmes de visibilité", icon: i(IconRadar), show: m("seo", "seo.read") },
    { group: "Visibilité", to: `${b}/ai-visibility`, label: "AI Visibility", icon: i(IconSparkles), show: m("geo", "geo.read") },
    { group: "Visibilité", to: `${b}/seo`, label: "SEO", icon: i(IconSearch), show: m("seo", "seo.read") },
    { group: "Visibilité", to: `${b}/geo`, label: "GEO", icon: i(IconWorldSearch), show: m("geo", "geo.read") },
    { group: "Visibilité", to: `${b}/opportunities`, label: "Opportunités", icon: i(IconTargetArrow), show: m("opportunities", "opportunities.read") },
    { group: "Contenus", to: `${b}/content`, label: "Content Studio", icon: i(IconPencil), show: m("content", "content.read") },
    { group: "Contenus", to: `${b}/pages`, label: "Pages", icon: i(IconLayout), show: m("pages", "pages.read") },
    { group: "Contenus", to: `${b}/social`, label: "Réseaux sociaux", icon: i(IconShare), show: m("social", "social.read") },
    { group: "Contenus", to: `${b}/video`, label: "Vidéo", icon: i(IconVideo), show: m("video", "video.read") },
    { group: "Vente", to: `${b}/prospects`, label: "Prospects", icon: i(IconUserSearch), show: m("prospects", "prospects.read") },
    { group: "Vente", to: `${b}/campaigns`, label: "Campagnes", icon: i(IconSend), show: m("prospects", "campaigns.read") },
    { group: "Vente", to: `${b}/email`, label: "E-mails", icon: i(IconMail), show: m("email_center", "email.read") },
    { group: "Vente", to: `${b}/whatsapp`, label: "WhatsApp", icon: i(IconBrandWhatsapp), show: m("whatsapp", "whatsapp.read") },
    { group: "Vente", to: `${b}/crm`, label: "CRM", icon: i(IconAddressBook), show: m("crm", "crm.read") },
    { group: "Automatisation", to: `${b}/scheduler`, label: t("nav.scheduler"), icon: i(IconCalendarTime), show: m("scheduler", "scheduler.read") },
    { group: "Automatisation", to: `${b}/workflows`, label: "Workflows", icon: i(IconGitBranch), show: m("workflows", "workflows.read") },
    { group: "Automatisation", to: `${b}/intelligence`, label: "Growth Intelligence", icon: i(IconBulb), show: m("intelligence", "intelligence.read") },
    { group: "Automatisation", to: `${b}/thor`, label: "THOR", icon: i(IconMessageChatbot), show: m("thor", "thor.use") },
    { group: "Administration", to: `${b}/products`, label: t("nav.products"), icon: i(IconBox), show: m("products", "products.read") },
    { group: "Administration", to: `${b}/websites`, label: t("nav.websites"), icon: i(IconWorld), show: m("websites", "websites.read") },
    { group: "Administration", to: `${b}/users`, label: "Utilisateurs & licences", icon: i(IconUsers), show: can("members.read") },
    { group: "Administration", to: `${b}/connectors`, label: t("nav.connectors"), icon: i(IconPlugConnected), show: can("connectors.read") },
    { group: "Administration", to: `${b}/subscription`, label: t("nav.subscription"), icon: i(IconCreditCard), show: can("licenses.read") },
    { group: "Administration", to: `${b}/history`, label: t("nav.history"), icon: i(IconHistory), show: can("history.read") },
    { group: "Administration", to: `${b}/settings`, label: t("nav.settings"), icon: i(IconSettings), show: true },
    { group: "Administration", to: "/pilot", label: t("nav.pilot"), icon: i(IconShieldLock), show: !!data?.user.is_pilot },
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
