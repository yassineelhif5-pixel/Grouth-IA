import { Alert, Badge, Button, Card, Code, Group, Select, SimpleGrid, Stack, Table, Text, Textarea, TextInput, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { dateCol, ModulePage, type Row, statusCol } from "@/features/ModulePage";
import { useTenant } from "@/hooks/useMe";
import { api } from "@/services/api";
import { formatDate } from "@/utils/format";

const useApi = <T,>(path: string, query?: Record<string, string | number | undefined>) => {
  const { tenantId } = useTenant();
  return useQuery({ queryKey: [path, tenantId, query], queryFn: () => api<T>(path, { tenantId, query }) });
};

// ───────────── SEO ─────────────
export function SeoPage() {
  const [cmp, setCmp] = useState<{ from: string; to: string }>({ from: "", to: "" });
  const { tenantId } = useTenant();
  const diff = useQuery({ queryKey: ["cmp", cmp], enabled: Boolean(cmp.from && cmp.to), queryFn: () => api<Row>("/seo/audits/compare", { tenantId, query: cmp }) });
  return (
    <Stack>
      <ModulePage title="SEO Intelligence — projets" endpoint="/seo/projects" module="seo" writePerm="seo.manage"
        columns={[{ key: "name", label: "Projet" }, statusCol(), dateCol()]}
        fields={[{ name: "name", label: "Nom", required: true }, { name: "product", label: "Produit (id)" }, { name: "website", label: "Site (id)" },
          { name: "target_country", label: "Pays" }, { name: "target_language", label: "Langue" }]}
        actions={[{ label: "Lancer un audit", path: (r) => `/seo/projects/${r.id}/audit`, perm: "seo.manage" }]} />
      <ModulePage title="Audits (historique conservé)" endpoint="/seo/audits" module="seo"
        columns={[dateCol(), statusCol(), { key: "score", label: "Score" }, { key: "pages_analyzed", label: "Pages" }, { key: "issues_count", label: "Problèmes" },
          { key: "id", label: "Comparer", render: (r) => <Group gap={4}><Button size="compact-xs" variant="subtle" onClick={() => setCmp({ ...cmp, from: r.id })}>De</Button>
            <Button size="compact-xs" variant="subtle" onClick={() => setCmp({ ...cmp, to: r.id })}>À</Button></Group> }]} />
      {diff.data && <Card withBorder><Title order={5}>Comparaison : Δ score {String(diff.data.score_delta)}</Title>
        <Text size="sm">Nouveaux problèmes : {(diff.data.new_issues as unknown[]).length} · Résolus : {(diff.data.resolved_issues as unknown[]).length} · Persistants : {String(diff.data.persisting)}</Text></Card>}
      <ModulePage title="Problèmes" endpoint="/seo/issues" module="seo" columns={[{ key: "issue_code", label: "Code" }, { key: "severity", label: "Sévérité", render: (r) => <StatusBadge value={r.severity as string} /> },
        { key: "page_url", label: "Page" }, { key: "description", label: "Description" }, statusCol()]} />
      <ModulePage title="Recommandations" endpoint="/seo/recommendations" module="seo" columns={[{ key: "priority", label: "P" }, { key: "title", label: "Recommandation" },
        { key: "impact", label: "Impact" }, { key: "difficulty", label: "Difficulté" }, statusCol()]} />
      <ModulePage title="Mots-clés" endpoint="/seo/keywords" module="seo" writePerm="seo.manage" columns={[{ key: "keyword", label: "Mot-clé" }, { key: "search_volume", label: "Volume" }, { key: "difficulty", label: "Difficulté" }]}
        fields={[{ name: "project", label: "Projet (id)", required: true }, { name: "keyword", label: "Mot-clé", required: true }, { name: "search_volume", label: "Volume", type: "number" }, { name: "difficulty", label: "Difficulté", type: "number" }]} />
    </Stack>
  );
}

// ───────────── GEO ─────────────
export function GeoPage() {
  const { tenantId } = useTenant();
  const [product, setProduct] = useState("");
  const obs = useQuery({ queryKey: ["geo", product], enabled: product.length === 36, queryFn: () => api<{ visibility: Row; observations: Row[] }>(`/geo/products/${product}`, { tenantId }) });
  return (
    <Stack>
      <ModulePage title="GEO — requêtes suivies" endpoint="/geo/queries" module="geo" writePerm="geo.manage"
        columns={[{ key: "query", label: "Question" }, { key: "engines", label: "Moteurs", render: (r) => ((r.engines as string[]) ?? []).join(", ") }, dateCol()]}
        fields={[{ name: "product", label: "Produit (id)", required: true }, { name: "query", label: "Question utilisateur", required: true },
          { name: "engines", label: "Moteurs (chatgpt, claude, gemini, perplexity, mistral)", type: "tags" }, { name: "competitor_names", label: "Concurrents", type: "tags" }, { name: "locale", label: "Langue" }]}
        actions={[{ label: "Interroger", path: (r) => `/geo/queries/${r.id}/run`, perm: "geo.manage" }]} />
      <Card withBorder>
        <Group align="flex-end"><TextInput label="Produit (id) pour les observations" value={product} onChange={(e) => setProduct(e.currentTarget.value)} w={380} />
          {product.length === 36 && <Button variant="light" onClick={() => api(`/geo/products/${product}`, { method: "POST", tenantId }).then(() => notifications.show({ message: "Audit GEO lancé" }))}>Audit GEO</Button>}</Group>
        {obs.data && <>
          <Text mt="sm">Visibilité observée : <b>{String(obs.data.visibility.visibility_score ?? "non mesurée")}</b> % ({String(obs.data.visibility.observations)} réponses, méthode API)</Text>
          <DataTable rows={obs.data.observations.map((o): Row => ({ ...o, id: String(o.run_id) }))} columns={[dateCol(), { key: "engine", label: "Moteur" }, { key: "model_code", label: "Modèle" },
            { key: "query", label: "Question" }, { key: "mentions", label: "Mentions", render: (r) => ((r.mentions as { brand: string }[] | null) ?? []).map((m) => m.brand).join(" → ") },
            { key: "citations", label: "Citations", render: (r) => ((r.citations as unknown[] | null) ?? []).length }, { key: "cost_cents", label: "Coût (cts)" }, statusCol()]} />
        </>}
      </Card>
      <ModulePage title="Recommandations GEO" endpoint="/geo/recommendations" module="geo" columns={[{ key: "priority", label: "P" }, { key: "title", label: "Recommandation" }, { key: "description", label: "Détail" }, statusCol()]} />
    </Stack>
  );
}

// ───────────── Content ─────────────
export const ContentPage = () => (
  <Stack>
    <ModulePage title="Content Studio" endpoint="/content/items" module="content" writePerm="content.write"
      columns={[{ key: "title", label: "Titre" }, { key: "content_type", label: "Format" }, statusCol(), { key: "seo_score", label: "SEO" }, { key: "geo_score", label: "GEO" },
        { key: "model_code", label: "Modèle" }, { key: "version_number", label: "v" }]}
      fields={[{ name: "project", label: "Projet (id)", required: true }, { name: "title", label: "Titre", required: true },
        { name: "content_type", label: "Format", type: "select", options: ["article", "guide", "tutorial", "comparison", "faq", "case_study", "product_page", "feature_page", "landing_page", "industry_page", "linkedin_post", "facebook_post", "instagram_post", "x_post", "newsletter", "video_script"] },
        { name: "keyword", label: "Mot-clé" }, { name: "objective", label: "Objectif" }, { name: "channel", label: "Canal" }, { name: "language", label: "Langue" }, { name: "body", label: "Contenu (Markdown)", type: "textarea" }]}
      actions={[{ label: "Générer (IA)", path: (r) => `/content/items/${r.id}/ai`, body: () => ({ operation: "generate" }), perm: "content.write" },
        { label: "Optimiser SEO", path: (r) => `/content/items/${r.id}/ai`, body: () => ({ operation: "optimize_seo" }), perm: "content.write" },
        { label: "Optimiser GEO", path: (r) => `/content/items/${r.id}/ai`, body: () => ({ operation: "optimize_geo" }), perm: "content.write" },
        { label: "Traduire", path: (r) => `/content/items/${r.id}/ai`, body: () => ({ operation: "translate", target_language: "en" }), perm: "content.write" },
        { label: "Versions", path: (r) => `/content/items/${r.id}/versions`, method: "GET" },
        { label: "Vérifier sources", path: (r) => `/content/items/${r.id}/sources` },
        { label: "Soumettre", path: (r) => `/content/items/${r.id}/workflow`, body: () => ({ op: "submit" }), show: (r) => r.status === "draft" },
        { label: "Valider", path: (r) => `/content/items/${r.id}/workflow`, body: () => ({ op: "approve" }), perm: "content.approve", show: (r) => r.status === "review" },
        { label: "Publier", path: (r) => `/content/items/${r.id}/publish`, prompt: "Id du connecteur CMS", body: () => ({}), perm: "content.publish", show: (r) => r.status === "approved" }]} />
    <ModulePage title="Projets de contenu" endpoint="/content/projects" module="content" writePerm="content.write" columns={[{ key: "name", label: "Projet" }, statusCol()]}
      fields={[{ name: "name", label: "Nom", required: true }, { name: "product", label: "Produit (id)", required: true }]} />
  </Stack>
);

export const PagesPage = () => {
  const { tenantId } = useTenant();
  return (
    <ModulePage title="Page Builder" endpoint="/pages" module="pages" writePerm="pages.write"
      columns={[{ key: "title", label: "Titre" }, { key: "page_type", label: "Type" }, { key: "slug", label: "Slug" }, statusCol(), { key: "published_url", label: "URL" }]}
      fields={[{ name: "title", label: "Titre", required: true }, { name: "slug", label: "Slug", required: true },
        { name: "page_type", label: "Type", type: "select", options: ["landing", "product", "feature", "comparison", "industry", "seo", "conversion"] },
        { name: "product", label: "Produit (id)" }, { name: "website", label: "Site (id)" }, { name: "connector_account", label: "Connecteur CMS (id)" },
        { name: "sections", label: "Sections [{type: hero|features|text|faq|cta|testimonials|pricing|comparison, props}]", type: "json" }, { name: "seo", label: "SEO {title, description}", type: "json" }]}
      defaultValues={{ sections: '[{"type":"hero","props":{"headline":"Titre","subheadline":"Sous-titre"}}]', seo: '{"title":"","description":""}' }}
      actions={[{ label: "Aperçu", path: (r) => `/pages/${r.id}/preview`, method: "GET", show: () => false },
        { label: "Soumettre", path: (r) => `/pages/${r.id}/workflow`, body: () => ({ op: "submit" }), show: (r) => r.status === "draft" },
        { label: "Valider", path: (r) => `/pages/${r.id}/workflow`, body: () => ({ op: "approve" }), show: (r) => r.status === "review" },
        { label: "Publier", path: (r) => `/pages/${r.id}/publish`, perm: "pages.publish", show: (r) => r.status === "approved" },
        { label: "Versions", path: (r) => `/pages/${r.id}/versions`, method: "GET" }]}
      extra={<Text size="xs" c="dimmed">Aperçu : ouvrir /api/v1/pages/&lt;id&gt;/preview (tenant {tenantId.slice(0, 8)})</Text>} />
  );
};

export const SocialPage = () => (
  <Stack>
    <ModulePage title="Publications sociales" endpoint="/social/publications" module="social" writePerm="social.write"
      columns={[{ key: "body", label: "Texte", render: (r) => String(r.body ?? "").slice(0, 80) }, statusCol(), dateCol("scheduled_at", "Programmée"), { key: "attempts", label: "Essais" },
        { key: "error_message", label: "Erreur" }, { key: "published_url", label: "URL" }]}
      fields={[{ name: "social_account", label: "Compte social (id)", required: true }, { name: "body", label: "Texte", type: "textarea" }, { name: "scheduled_at", label: "Programmer (ISO)" },
        { name: "status", label: "Statut", type: "select", options: ["draft", "scheduled"] }]}
      actions={[{ label: "Publier", path: (r) => `/social/publications/${r.id}/publish`, perm: "social.publish", show: (r) => r.status !== "published" }]} />
    <ModulePage title="Comptes sociaux" endpoint="/social/accounts" module="social" writePerm="social.write" columns={[{ key: "platform", label: "Plateforme" }, { key: "handle", label: "Compte" }, statusCol()]}
      fields={[{ name: "platform", label: "Plateforme", type: "select", options: ["linkedin", "facebook", "instagram", "x", "youtube", "tiktok", "pinterest"] }, { name: "handle", label: "Identifiant", required: true },
        { name: "connector_account", label: "Connecteur (id)" }, { name: "product", label: "Produit (id)" }]} />
  </Stack>
);

export const VideoPage = () => (
  <ModulePage title="Video Studio" endpoint="/video/projects" module="video" writePerm="video.write"
    columns={[{ key: "title", label: "Projet" }, { key: "format", label: "Format" }, statusCol(), dateCol()]}
    fields={[{ name: "product", label: "Produit (id)", required: true }, { name: "title", label: "Titre", required: true }, { name: "format", label: "Format", type: "select", options: ["short", "long"] }]}
    actions={[{ label: "Script + storyboard (IA)", path: (r) => `/video/projects/${r.id}/script`, prompt: "Brief" },
      { label: "Rendu vidéo", path: (r) => `/video/projects/${r.id}/render`, body: () => ({}) }]}
    extra={<Text size="xs" c="dimmed">Un script n'est pas une vidéo : le rendu exige un fournisseur vidéo connecté.</Text>} />
);

// ───────────── Opportunities ─────────────
export function OpportunitiesPage() {
  const { tenantId, can } = useTenant();
  const qc = useQueryClient();
  const [status, setStatus] = useState<string | null>(null);
  const board = useApi<Row[]>("/opportunities", { status: status ?? "" });
  const move = useMutation({ mutationFn: (b: Row) => api("/opportunities", { method: "POST", body: b, tenantId }), onSuccess: () => void qc.invalidateQueries({ queryKey: ["/opportunities"] }) });
  return (
    <Stack>
      <ModulePage title="Opportunity Hunter — recherches" endpoint="/opportunities/projects" module="opportunities" writePerm="opportunities.manage"
        columns={[{ key: "name", label: "Recherche" }, { key: "hunters", label: "Hunters", render: (r) => ((r.hunters as string[]) ?? []).join(", ") }, statusCol()]}
        fields={[{ name: "name", label: "Nom", required: true }, { name: "product", label: "Produit (id)" }, { name: "hunters", label: "Hunters (keyword, website, competitor, content_gap, customer)", type: "tags" }]}
        actions={[{ label: "Chasser", path: (r) => `/opportunities/projects/${r.id}/hunt`, perm: "opportunities.manage" }]} />
      <PageHeader title="Opportunités détectées" actions={<Select placeholder="Statut" clearable value={status} onChange={setStatus}
        data={["new", "detected", "under_analysis", "qualified", "approved", "in_progress", "won", "rejected", "archived"]} />} />
      <DataTable rows={board.data} loading={board.isLoading} error={board.error} columns={[{ key: "kind", label: "Type" }, { key: "title", label: "Opportunité" },
        { key: "score", label: "Score" }, { key: "confidence", label: "Confiance" }, { key: "evidence_count", label: "Preuves" }, statusCol(),
        { key: "x", label: "Décision", render: (r) => can("opportunities.manage") && <Select size="xs" w={150} placeholder="Changer…" data={["under_analysis", "qualified", "approved", "in_progress", "won", "rejected", "archived"]}
          onChange={(v) => { const reason = v && window.prompt("Motif"); if (v && reason) move.mutate({ kind: r.kind, id: r.id, status: v, reason } as Row); }} /> }]} />
      <ModulePage title="Social Opportunity Hunter — veilles" endpoint="/social-hunter/configs" module="social_hunter" writePerm="opportunities.manage"
        columns={[{ key: "name", label: "Veille" }, { key: "keywords", label: "Mots-clés", render: (r) => ((r.keywords as string[]) ?? []).join(", ") }, dateCol("last_run_at", "Dernière"), statusCol()]}
        fields={[{ name: "name", label: "Nom", required: true }, { name: "keywords", label: "Mots-clés", type: "tags" }, { name: "negative_keywords", label: "Exclusions", type: "tags" },
          { name: "sources", label: "Sources (hackernews, rss:<url>)", type: "tags" }, { name: "frequency", label: "Fréquence", type: "select", options: ["hourly", "daily", "weekly"] }]}
        actions={[{ label: "Lancer", path: (r) => `/social-hunter/configs/${r.id}/run` }]} />
      <ModulePage title="Signaux publics" endpoint="/social-hunter/signals" module="social_hunter"
        columns={[{ key: "source", label: "Source" }, { key: "title", label: "Titre" }, { key: "intent", label: "Intention" }, { key: "score", label: "Score" }, statusCol(),
          { key: "url", label: "Lien", render: (r) => <a href={String(r.url)} target="_blank" rel="noreferrer">ouvrir</a> }]}
        actions={[{ label: "→ Prospect", path: (r) => `/social-hunter/signals/${r.id}/to_prospect`, perm: "opportunities.manage", show: (r) => r.status !== "converted" }]}
        extra={<Text size="xs" c="dimmed">Une conversation publique ne vaut pas consentement à la prospection.</Text>} />
    </Stack>
  );
}

// ───────────── Smart Prospect / Campaigns / CRM ─────────────
export function ProspectsPage() {
  const { tenantId } = useTenant();
  const [csv, setCsv] = useState("company,industry,country,first_name,last_name,email,job_title,consent_status\n");
  const imp = useMutation({ mutationFn: () => api<Row>("/prospects/items/import", { method: "POST", body: { csv }, tenantId }), onSuccess: (r) => notifications.show({ message: JSON.stringify(r) }) });
  return (
    <Stack>
      <ModulePage title="Smart Prospect — prospects" endpoint="/prospects/items" module="prospects" writePerm="prospects.write"
        columns={[{ key: "status", label: "Pipeline", render: (r) => <StatusBadge value={r.status as string} /> }, { key: "score", label: "Score" }, { key: "confidence", label: "Confiance" },
          { key: "need_detected", label: "Besoin" }, { key: "source_detail", label: "Source" }, dateCol("last_activity_at", "Dernière activité")]}
        fields={[{ name: "project", label: "Projet (id)" }, { name: "company", label: "Entreprise (id)" }, { name: "need_detected", label: "Besoin détecté" }]}
        actions={[{ label: "Qualifier", path: (r) => `/prospects/items/${r.id}/qualify` }, { label: "Timeline", path: (r) => `/prospects/items/${r.id}/timeline`, method: "GET" },
          { label: "Affecter", path: (r) => `/prospects/items/${r.id}/assign`, prompt: "Id utilisateur", body: () => ({}) }]} />
      <Card withBorder><Title order={5}>Import CSV (sources autorisées uniquement)</Title>
        <Textarea autosize minRows={3} value={csv} onChange={(e) => setCsv(e.currentTarget.value)} /><Button mt="xs" onClick={() => imp.mutate()} loading={imp.isPending}>Importer</Button></Card>
      <ModulePage title="Projets / ICP" endpoint="/prospects/projects" module="prospects" writePerm="prospects.write" columns={[{ key: "name", label: "Projet" }, statusCol()]}
        fields={[{ name: "name", label: "Nom", required: true }, { name: "icp", label: "ICP {industries, company_sizes, countries, functions, technologies}", type: "json" }]}
        defaultValues={{ icp: '{"industries":[],"company_sizes":["11-50"],"countries":["FR"],"functions":["CEO"]}' }} />
      <ModulePage title="Entreprises" endpoint="/prospects/companies" module="prospects" writePerm="prospects.write" columns={[{ key: "name", label: "Entreprise" }, { key: "industry", label: "Secteur" }, { key: "size_employees", label: "Taille" }, { key: "country_code", label: "Pays" }]}
        fields={[{ name: "name", label: "Nom", required: true }, { name: "domain", label: "Domaine" }, { name: "industry", label: "Secteur" }, { name: "size_employees", label: "Effectif", type: "number" }, { name: "country_code", label: "Pays (ISO2)" }]} />
      <ModulePage title="Segments" endpoint="/prospects/segments" module="prospects" writePerm="prospects.write" columns={[{ key: "name", label: "Segment" }]}
        fields={[{ name: "name", label: "Nom", required: true }, { name: "project", label: "Projet (id)" }, { name: "criteria", label: "Critères {min_score, status, industry, country}", type: "json" }]} />
    </Stack>
  );
}

export const CampaignsPage = () => (
  <Stack>
    <ModulePage title="Campagnes" endpoint="/campaigns" module="prospects" writePerm="campaigns.manage"
      columns={[{ key: "name", label: "Campagne" }, { key: "channel", label: "Canal" }, statusCol(), dateCol()]}
      fields={[{ name: "name", label: "Nom", required: true }, { name: "project", label: "Projet (id)" }, { name: "segment", label: "Segment (id)" }, { name: "mailbox", label: "Boîte d'envoi (id)" },
        { name: "channel", label: "Canal", type: "select", options: ["email", "whatsapp"] }]}
      actions={[{ label: "Lancer", path: (r) => `/campaigns/${r.id}/launch`, show: (r) => r.status === "draft" || r.status === "paused" },
        { label: "Pause", path: (r) => `/campaigns/${r.id}/pause`, show: (r) => r.status === "running" }]} />
    <ModulePage title="Modèles" endpoint="/prospects/templates" module="prospects" writePerm="campaigns.manage" columns={[{ key: "name", label: "Modèle" }, { key: "channel", label: "Canal" }, { key: "subject", label: "Sujet" }]}
      fields={[{ name: "name", label: "Nom", required: true }, { name: "channel", label: "Canal", type: "select", options: ["email", "whatsapp"] }, { name: "subject", label: "Sujet ({{first_name}})" }, { name: "body", label: "Corps", type: "textarea" }]} />
    <ModulePage title="Séquences" endpoint="/prospects/sequences" module="prospects" writePerm="campaigns.manage" columns={[{ key: "step", label: "Étape" }, { key: "delay_hours", label: "Délai (h)" }]}
      fields={[{ name: "campaign", label: "Campagne (id)", required: true }, { name: "step", label: "Étape", type: "number" }, { name: "template", label: "Modèle (id)" }, { name: "delay_hours", label: "Délai (h)", type: "number" }]} />
  </Stack>
);

export function CrmPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const pipe = useApi<{ prospects_by_status: Row[]; stages: Row[] }>("/crm/pipeline");
  const init = useMutation({ mutationFn: () => api("/crm/pipeline", { method: "POST", body: {}, tenantId }), onSuccess: () => void qc.invalidateQueries({ queryKey: ["/crm/pipeline"] }) });
  return (
    <Stack>
      <PageHeader title="CRM" actions={!pipe.data?.stages.length && <Button onClick={() => init.mutate()}>Initialiser le pipeline</Button>} />
      <SimpleGrid cols={{ base: 2, md: 5 }}>{pipe.data?.stages.map((s) => (
        <Card key={s.id} withBorder><Text size="sm" fw={600}>{String(s.name)}</Text><Text size="xs">{String(s.opportunities)} opp. · {(Number(s.amount_cents) / 100).toFixed(0)} €</Text></Card>))}</SimpleGrid>
      <Group>{pipe.data?.prospects_by_status.map((p) => <Badge key={String(p.status)} variant="light">{String(p.status)} : {String(p.n)}</Badge>)}</Group>
      <ModulePage title="Opportunités commerciales" endpoint="/crm/opportunities" module="crm" writePerm="crm.write" columns={[{ key: "title", label: "Opportunité" }, { key: "amount_cents", label: "Montant (cts)" }, dateCol("expected_close_date", "Clôture")]}
        fields={[{ name: "title", label: "Titre", required: true }, { name: "stage", label: "Étape (id)", required: true }, { name: "prospect", label: "Prospect (id)" }, { name: "amount_cents", label: "Montant (cts)", type: "number" }]} />
      <ModulePage title="Tâches" endpoint="/crm/tasks" module="crm" writePerm="crm.write" columns={[{ key: "title", label: "Tâche" }, dateCol("due_at", "Échéance"), statusCol()]}
        fields={[{ name: "title", label: "Titre", required: true }, { name: "due_at", label: "Échéance (ISO)" }]} />
      <ModulePage title="Rendez-vous" endpoint="/crm/meetings" module="crm" writePerm="crm.write" columns={[{ key: "title", label: "Rendez-vous" }, dateCol("starts_at", "Début"), { key: "location", label: "Lieu" }]}
        fields={[{ name: "title", label: "Titre", required: true }, { name: "starts_at", label: "Début (ISO)", required: true }, { name: "location", label: "Lieu" }]} />
      <ModulePage title="Activités (timeline)" endpoint="/crm/activities" module="crm" writePerm="crm.write" columns={[dateCol(), { key: "activity_type", label: "Type" }, { key: "summary", label: "Résumé" }, { key: "actor_type", label: "Acteur" }]}
        fields={[{ name: "prospect", label: "Prospect (id)" }, { name: "activity_type", label: "Type", type: "select", options: ["call", "note", "meeting", "task"] }, { name: "summary", label: "Résumé", type: "textarea" }]} />
    </Stack>
  );
}

// ───────────── Email Center ─────────────
const FOLDERS = ["inbox", "unread", "replies", "interested", "demo_requested", "follow_up", "sent", "drafts", "bounced", "failed", "unsubscribed", "archived"];

export function EmailCenterPage() {
  const { tenantId, can } = useTenant();
  const qc = useQueryClient();
  const [folder, setFolder] = useState("inbox");
  const [conv, setConv] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const list = useApi<Row[]>(`/email/folders/${folder}`);
  const tl = useQuery({ queryKey: ["conv", conv], enabled: Boolean(conv), queryFn: () => api<{ messages: Row[]; drafts: Row[]; activities: Row[] }>(`/email/conversations/${conv}`, { tenantId }) });
  const report = useApi<Row>("/email/report");
  const act = useMutation({
    mutationFn: (b: Record<string, unknown>) => api(`/email/conversations/${conv}`, { method: "POST", body: b, tenantId }),
    onSuccess: () => { setReply(""); void qc.invalidateQueries({ queryKey: ["conv", conv] }); void qc.invalidateQueries({ queryKey: [`/email/folders/${folder}`] }); },
  });
  return (
    <Stack>
      <PageHeader title="Email Center" subtitle={report.data ? `Envoyés ${String(report.data.sent)} · acceptés ${String(report.data.accepted)} · délivrés confirmés ${String(report.data.delivered_confirmed)} · réponses ${String(report.data.replies)} · positives ${String(report.data.positive_replies)} · démos ${String(report.data.demo_requests)} · désabonnements ${String(report.data.unsubscribes)}` : undefined} />
      <Group gap={4}>{FOLDERS.map((f) => <Button key={f} size="xs" variant={f === folder ? "filled" : "light"} onClick={() => { setFolder(f); setConv(null); }}>{f.replace("_", " ")}</Button>)}</Group>
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <DataTable rows={list.data} loading={list.isLoading} error={list.error} onRowClick={(r) => setConv(r.id)} empty="Aucune conversation"
          columns={[{ key: "subject", label: "Sujet", render: (r) => <Text fw={r.is_unread ? 700 : 400} size="sm">{String(r.subject ?? "")}</Text> },
            { key: "lm", label: "Dernier message", render: (r) => { const m = r.last_message as Row | null; return m ? `${String(m.direction)} · ${String(m.from)}` : "—"; } },
            { key: "campaign", label: "Campagne" }, { key: "prospect_status", label: "Prospect" }, dateCol("last_message_at", "Date")]} />
        {conv && tl.data && <Card withBorder>
          <Stack gap="xs">
            {tl.data.messages.map((m) => (
              <Card key={m.id} withBorder bg={m.direction === "inbound" ? "var(--mantine-color-blue-light)" : undefined}>
                <Group justify="space-between"><Text size="xs">{String(m.direction)} · {String(m.from_email)} → {((m.to_emails as string[]) ?? []).join(", ")}</Text><StatusBadge value={m.status as string} /></Group>
                <Text size="xs" c="dimmed">{formatDate((m.received_at ?? m.sent_at ?? m.created_at) as string)} · {String(m.message_id_header)}</Text>
                <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{String(m.body_text ?? "").slice(0, 3000)}</Text>
                {m.ai ? <Alert mt="xs" color="violet" title={`THOR : ${String((m.ai as Row).category)} (${String((m.ai as Row).method)})`}>{String((m.ai as Row).summary ?? "")} {(m.ai as Row).next_action ? `→ ${String((m.ai as Row).next_action)}` : ""}</Alert> : null}
              </Card>))}
            {tl.data.drafts.filter((d) => d.status === "draft").map((d) => (
              <Card key={d.id} withBorder><Text size="xs" c="dimmed">Brouillon THOR ({String(d.model_code)}) — jamais envoyé automatiquement</Text>
                <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{String(d.body)}</Text>
                {can("email.send") && <Button mt="xs" size="xs" onClick={() => act.mutate({ action: "send_draft", draft_id: d.id })}>Relire et envoyer</Button>}</Card>))}
            {tl.data.activities.map((a, i) => <Text key={i} size="xs" c="dimmed">{formatDate(a.created_at as string)} · {String(a.activity_type)} · {String(a.summary)}</Text>)}
            {can("email.send") && <>
              <Textarea placeholder="Votre réponse" autosize minRows={3} value={reply} onChange={(e) => setReply(e.currentTarget.value)} />
              <Group gap={4}>
                <Button size="xs" disabled={!reply} onClick={() => act.mutate({ action: "reply", body: reply })}>Répondre</Button>
                <Button size="xs" variant="light" disabled={!reply} onClick={() => act.mutate({ action: "reply_all", body: reply })}>Répondre à tous</Button>
                <Button size="xs" variant="light" onClick={() => act.mutate({ action: "draft" })}>Brouillon THOR</Button>
                <Button size="xs" variant="default" onClick={() => { const t = window.prompt("Note interne"); if (t) act.mutate({ action: "note", text: t }); }}>Note</Button>
                <Button size="xs" variant="default" onClick={() => { const u = window.prompt("Id du commercial"); if (u) act.mutate({ action: "assign", user_id: u }); }}>Affecter</Button>
                <Button size="xs" variant="default" onClick={() => { const t = window.prompt("Tâche"); if (t) act.mutate({ action: "task", title: t }); }}>Tâche</Button>
                <Button size="xs" variant="default" onClick={() => { const d = window.prompt("Rendez-vous (ISO, ex 2026-12-01T10:00)"); if (d) act.mutate({ action: "meeting", title: "Rendez-vous", starts_at: d }); }}>Rendez-vous</Button>
                <Button size="xs" variant="default" onClick={() => act.mutate({ action: "unread" })}>Non lu</Button>
                <Button size="xs" variant="default" onClick={() => act.mutate({ action: "archive" })}>Archiver</Button>
              </Group></>}
          </Stack>
        </Card>}
      </SimpleGrid>
      <ModulePage title="Boîtes mail" endpoint="/email/mailboxes" module="email_center" writePerm="email.manage"
        columns={[{ key: "address", label: "Adresse" }, { key: "receive_mode", label: "Réception" }, statusCol(), dateCol("last_sync_at", "Dernière synchro"), { key: "sync_error", label: "Erreur" }]}
        fields={[{ name: "provider_account", label: "Compte fournisseur (id)", required: true }, { name: "address", label: "Adresse", required: true }, { name: "display_name", label: "Nom affiché" },
          { name: "connector_account", label: "Connecteur (id)" }, { name: "receive_mode", label: "Réception", type: "select", options: ["none", "webhook", "gmail", "graph", "imap"] }]}
        actions={[{ label: "Synchroniser", path: (r) => `/email/mailboxes/${r.id}/sync`, perm: "email.manage" }]} />
    </Stack>
  );
}

// ───────────── WhatsApp ─────────────
export function WhatsAppPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [conv, setConv] = useState<string | null>(null);
  const [text, setText] = useState("");
  const list = useApi<Row[]>("/whatsapp/conversations");
  const msgs = useQuery({ queryKey: ["wa", conv], enabled: Boolean(conv), queryFn: () => api<Row[]>(`/whatsapp/conversations/${conv}`, { tenantId }) });
  const send = useMutation({ mutationFn: (b: Record<string, unknown>) => api(`/whatsapp/conversations/${conv}`, { method: "POST", body: b, tenantId }),
    onSuccess: () => { setText(""); void qc.invalidateQueries({ queryKey: ["wa", conv] }); } });
  return (
    <Stack>
      <PageHeader title="WhatsApp Center" subtitle="Messages libres uniquement dans la fenêtre de 24 h et avec opt-in ; sinon modèles approuvés." />
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <DataTable rows={list.data} loading={list.isLoading} error={list.error} onRowClick={(r) => setConv(r.id)} columns={[{ key: "display_name", label: "Contact" }, { key: "wa_id", label: "Numéro" },
          { key: "consent_status", label: "Consentement", render: (r) => <StatusBadge value={r.consent_status as string} /> }, { key: "window_open", label: "Fenêtre 24h", render: (r) => (r.window_open ? "ouverte" : "fermée") },
          { key: "last_message", label: "Dernier message" }]} />
        {conv && <Card withBorder><Stack gap={4}>
          {msgs.data?.map((m) => <Text key={m.id} size="sm" ta={m.direction === "outbound" ? "right" : "left"}>{String(m.body ?? m.template_name)} <Badge size="xs">{String(m.status)}</Badge></Text>)}
          <TextInput placeholder="Message" value={text} onChange={(e) => setText(e.currentTarget.value)} />
          <Group gap={4}><Button size="xs" disabled={!text} onClick={() => send.mutate({ text })}>Envoyer</Button>
            <Button size="xs" variant="default" onClick={() => send.mutate({ action: "consent", consent_status: "opted_in", source: window.prompt("Source du consentement (preuve)") ?? "" })}>Enregistrer un opt-in</Button>
            <Button size="xs" variant="default" onClick={() => { const t = window.prompt("Nom du modèle approuvé"); if (t) send.mutate({ template: t, language: "fr" }); }}>Modèle</Button></Group>
        </Stack></Card>}
      </SimpleGrid>
      <ModulePage title="Comptes WhatsApp" endpoint="/whatsapp/accounts" module="whatsapp" writePerm="whatsapp.send" columns={[{ key: "display_phone", label: "Numéro" }, { key: "phone_number_id", label: "Phone number id" }, statusCol()]}
        fields={[{ name: "phone_number_id", label: "Phone number id", required: true }, { name: "waba_id", label: "WABA id" }, { name: "display_phone", label: "Numéro affiché" }, { name: "connector_account", label: "Connecteur (id)" }]} />
      <ModulePage title="Modèles approuvés" endpoint="/whatsapp/templates" module="whatsapp" writePerm="whatsapp.send" columns={[{ key: "name", label: "Nom" }, { key: "language", label: "Langue" }, statusCol()]}
        fields={[{ name: "account", label: "Compte (id)", required: true }, { name: "name", label: "Nom", required: true }, { name: "language", label: "Langue" }, { name: "status", label: "Statut", type: "select", options: ["pending", "approved", "rejected"] }]} />
    </Stack>
  );
}

// ───────────── Scheduler & Workflows ─────────────
type Pick = { value: string; label: string };
const asList = (d: unknown): Row[] => (Array.isArray(d) ? d : ((d as { results?: Row[] })?.results ?? [])) as Row[];
const labelOf = (r: Row): string => String(r.name ?? r.title ?? r.domain ?? r.url ?? r.id);

/** Guided scheduling of SEO / GEO / Smart Prospect sessions: pick the target in a list, no JSON. */
type SessionKind = { label: string; source: string; param: string; target: string };
const SEO_KIND: SessionKind = { label: "Audit SEO", source: "/seo/projects", param: "project_id", target: "Projet SEO" };
const SESSION_KINDS: Record<string, SessionKind> = {
  seo: SEO_KIND,
  geo: { label: "Visibilité GEO (IA)", source: "/products", param: "product_id", target: "Produit" },
  prospects: { label: "Smart Prospect (campagne)", source: "/campaigns", param: "campaign_id", target: "Campagne" },
};

function QuickScheduleCard() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [kind, setKind] = useState("seo");
  const [target, setTarget] = useState<string | null>(null);
  const [freq, setFreq] = useState("daily");
  const [value, setValue] = useState("08:30");
  const [mode, setMode] = useState("automatic");
  const [name, setName] = useState("");
  const k = SESSION_KINDS[kind] ?? SEO_KIND;
  const targets = useQuery({ queryKey: [k.source, tenantId, "pick"], queryFn: () => api<unknown>(k.source, { tenantId, query: { page_size: 200 } }) });
  const options: Pick[] = asList(targets.data).map((r) => ({ value: String(r.id), label: labelOf(r) }));
  const create = useMutation({
    mutationFn: () => api<Row>("/schedulers", { method: "POST", tenantId, body: {
      name: name.trim() || `${k.label} — ${options.find((o) => o.value === target)?.label ?? ""}`,
      category: kind, frequency_type: freq, frequency_value: freq === "hourly" ? null : value, timezone: "Europe/Paris", mode,
      product: kind === "geo" ? target : undefined, params: { [k.param]: target } } }),
    onSuccess: () => { setTarget(null); setName(""); notifications.show({ color: "green", message: "Séance programmée" }); void qc.invalidateQueries({ queryKey: ["/schedulers"] }); },
  });
  const hint: Record<string, string> = { daily: "Heure HH:MM, ex. 08:30", weekly: "Jour et heure, ex. monday 08:30", monthly: "Jour et heure, ex. 1 08:30",
    every_x_hours: "Nombre d'heures, ex. 6", cron: "Expression cron, ex. 0 8 * * 1-5" };
  return (
    <Card withBorder mb="md">
      <Title order={5} mb="sm">Programmer une séance SEO, GEO ou Smart Prospect</Title>
      <SimpleGrid cols={{ base: 1, md: 3 }}>
        <Select label="Type de séance" value={kind} allowDeselect={false} onChange={(v) => { setKind(v ?? "seo"); setTarget(null); }}
          data={Object.entries(SESSION_KINDS).map(([v, x]) => ({ value: v, label: x.label }))} />
        <Select label={k.target} value={target} onChange={setTarget} data={options} searchable
          placeholder={targets.isLoading ? "Chargement…" : options.length ? "Choisir" : `Aucun élément : créez d'abord un ${k.target.toLowerCase()}`} />
        <TextInput label="Nom (optionnel)" value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <Select label="Fréquence" value={freq} allowDeselect={false} onChange={(v) => setFreq(v ?? "daily")} data={[
          { value: "hourly", label: "Toutes les heures" }, { value: "every_x_hours", label: "Toutes les X heures" },
          { value: "daily", label: "Chaque jour" }, { value: "weekly", label: "Chaque semaine" }, { value: "monthly", label: "Chaque mois" },
          { value: "cron", label: "Avancé (cron)" }]} />
        {freq !== "hourly" && <TextInput label="Quand" description={hint[freq]} value={value} onChange={(e) => setValue(e.currentTarget.value)} />}
        <Select label="Mode" value={mode} allowDeselect={false} onChange={(v) => setMode(v ?? "automatic")} data={[
          { value: "automatic", label: "Automatique" }, { value: "approval", label: "Avec validation" }, { value: "analysis", label: "Analyse seule" }]} />
      </SimpleGrid>
      <Group mt="md"><Button onClick={() => create.mutate()} loading={create.isPending} disabled={!target}>Programmer</Button></Group>
    </Card>
  );
}

export const SchedulerV2Page = () => (
  <>
  <QuickScheduleCard />
  <ModulePage title="Multi-Scheduler" endpoint="/schedulers" module="scheduler" writePerm="scheduler.manage"
    columns={[{ key: "name", label: "Programmation" }, { key: "category", label: "Catégorie" }, { key: "frequency_type", label: "Fréquence" }, { key: "mode", label: "Mode" }, statusCol(),
      dateCol("next_run_at", "Prochaine"), dateCol("last_run_at", "Dernière"), { key: "last_status", label: "Résultat", render: (r) => <StatusBadge value={r.last_status as string} /> }]}
    fields={[{ name: "name", label: "Nom", required: true }, { name: "product", label: "Produit (id)" },
      { name: "category", label: "Catégorie", type: "select", options: ["seo", "geo", "articles", "pages", "social", "videos", "opportunities", "social_monitoring", "prospects", "crm", "reporting", "intelligence", "agents"] },
      { name: "frequency_type", label: "Fréquence", type: "select", options: ["hourly", "every_x_hours", "daily", "weekly", "monthly", "cron", "event", "conditional"] },
      { name: "frequency_value", label: "Valeur (X | HH:MM | jour HH:MM | cron | évènement)" }, { name: "timezone", label: "Fuseau" },
      { name: "mode", label: "Mode", type: "select", options: ["automatic", "approval", "analysis"] }, { name: "budget_cents", label: "Budget mensuel (cts)", type: "number" },
      { name: "params", label: "Paramètres (JSON)", type: "json" }]}
    defaultValues={{ timezone: "Europe/Paris", frequency_type: "daily", frequency_value: "08:30", mode: "approval", params: "{}" }}
    actions={[{ label: "Exécuter", path: (r) => `/schedulers/${r.id}/run` }, { label: "Historique", path: (r) => `/schedulers/${r.id}/runs`, method: "GET" }]} />
  </>
);

export const WorkflowsPage = () => (
  <ModulePage title="Workflows" endpoint="/workflows" module="workflows" writePerm="workflows.manage"
    columns={[{ key: "name", label: "Workflow" }, statusCol(), dateCol("updated_at", "Modifié"), { key: "version_number", label: "v" }]}
    fields={[{ name: "name", label: "Nom", required: true }, { name: "status", label: "Statut", type: "select", options: ["draft", "active", "archived"] },
      { name: "definition", label: "Définition {start, nodes:[{key,type,params,next,on_failure,on_true,on_false}]}", type: "json" }]}
    defaultValues={{ status: "draft", definition: '{"start":"scan","nodes":[{"key":"scan","type":"seo_scan","params":{"project_id":""},"next":"opps"},{"key":"opps","type":"detect_opportunities","params":{"project_id":""},"next":"ok"},{"key":"ok","type":"approval","next":"tell"},{"key":"tell","type":"notify","params":{"message":"Workflow terminé"}}]}' }}
    actions={[{ label: "Exécuter", path: (r) => `/workflows/${r.id}/run`, body: () => ({ input: {} }), show: (r) => r.status === "active" },
      { label: "Exécutions", path: (r) => `/workflows/${r.id}/executions`, method: "GET" }]} />
);

// ───────────── Intelligence, THOR, Approvals, Reporting, Connectors ─────────────
export function IntelligencePage() {
  const { tenantId, can } = useTenant();
  const qc = useQueryClient();
  const q = useApi<{ recommendations: Row[]; snapshot: Row | null; learning: Row[] }>("/intelligence");
  const run = useMutation({ mutationFn: (b: Row | Record<string, unknown>) => api("/intelligence", { method: "POST", body: b, tenantId }), onSuccess: () => void qc.invalidateQueries({ queryKey: ["/intelligence"] }) });
  return (
    <Stack>
      <PageHeader title="Growth Intelligence" subtitle="Observer → détecter → prioriser → décider → mesurer → apprendre" actions={can("intelligence.manage") && <Button onClick={() => run.mutate({})} loading={run.isPending}>Lancer un cycle</Button>} />
      {q.data?.recommendations.map((r) => (
        <Card key={r.id} withBorder>
          <Group justify="space-between"><Text fw={600}>{String(r.title)}</Text><Group gap={4}><Badge>{String(r.nature)}</Badge><Badge color="orange">impact {String(r.impact)}</Badge><Badge color="gray">difficulté {String(r.difficulty)}</Badge><StatusBadge value={r.status as string} /></Group></Group>
          <Text size="sm">{String(r.justification)} · confiance {String(r.confidence)}</Text>
          <Text size="xs" c="dimmed">Actions : {((r.actions as string[]) ?? []).join(" · ")} {((r.risks as string[]) ?? []).length ? `· Risques : ${((r.risks as string[]) ?? []).join(", ")}` : ""}</Text>
          <Code block mt={4}>{JSON.stringify(r.sources)}</Code>
          {r.status === "open" && can("intelligence.manage") && <Group mt="xs" gap={4}><Button size="xs" onClick={() => run.mutate({ op: "decide", id: r.id, accept: true, comment: "accepté" })}>Accepter</Button>
            <Button size="xs" variant="default" onClick={() => run.mutate({ op: "decide", id: r.id, accept: false, comment: window.prompt("Motif") ?? "" })}>Rejeter</Button></Group>}
        </Card>))}
      {q.data?.learning.map((l, i) => <Text key={i} size="xs">{formatDate(l.created_at as string)} · {String(l.lesson)}</Text>)}
    </Stack>
  );
}

export function ThorPage() {
  const { tenantId } = useTenant();
  const [cid, setCid] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const convs = useApi<Row[]>("/thor/chat");
  const thread = useQuery({ queryKey: ["thor", cid], enabled: Boolean(cid), queryFn: () => api<Row[]>("/thor/chat", { tenantId, query: { conversation_id: cid ?? "" } }) });
  const qc = useQueryClient();
  const ask = useMutation({ mutationFn: () => api<Row>("/thor/chat", { method: "POST", body: { message: msg, conversation_id: cid }, tenantId }),
    onSuccess: (r) => { setMsg(""); setCid(String(r.conversation_id)); void qc.invalidateQueries({ queryKey: ["thor"] }); void qc.invalidateQueries({ queryKey: ["/thor/chat"] }); } });
  return (
    <Stack>
      <PageHeader title="THOR" subtitle="Assistant de croissance — agit uniquement avec vos permissions ; conversations conservées." />
      <SimpleGrid cols={{ base: 1, lg: 3 }}>
        <Card withBorder><Stack gap={4}><Button size="xs" variant="light" onClick={() => setCid(null)}>Nouvelle conversation</Button>
          {convs.data?.map((c) => <Button key={c.id} size="xs" variant={c.id === cid ? "filled" : "subtle"} onClick={() => setCid(c.id)}>{String(c.title).slice(0, 40)}</Button>)}</Stack></Card>
        <Card withBorder style={{ gridColumn: "span 2" }}><Stack gap="xs">
          {thread.data?.map((m) => <Card key={m.id} withBorder bg={m.role === "user" ? "var(--mantine-color-gray-light)" : undefined}>
            <Text size="xs" c="dimmed">{String(m.role)} {m.model_code ? `· ${String(m.model_code)} · ${String(m.duration_ms)} ms` : ""} {m.tools ? `· outils : ${(m.tools as Row[]).map((t) => `${String(t.tool)}(${String(t.status)})`).join(", ")}` : ""}</Text>
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{String(m.content)}</Text></Card>)}
          <Textarea autosize minRows={2} value={msg} onChange={(e) => setMsg(e.currentTarget.value)} placeholder="Demandez à THOR…" />
          <Button onClick={() => ask.mutate()} loading={ask.isPending} disabled={!msg}>Envoyer</Button>
        </Stack></Card>
      </SimpleGrid>
    </Stack>
  );
}

export const ApprovalsPage = () => (
  <ModulePage title="Validations en attente" endpoint="/approvals" module="permissions"
    columns={[dateCol(), { key: "module_code", label: "Module" }, { key: "action_code", label: "Action" }, { key: "requested_by_agent", label: "Agent" }, statusCol(), dateCol("expires_at", "Expire")]}
    actions={[{ label: "Approuver", path: (r) => `/approvals/${r.id}/decide`, prompt: "Motif de validation", body: () => ({ approve: true }), perm: "approvals.decide" },
      { label: "Rejeter", path: (r) => `/approvals/${r.id}/decide`, prompt: "Motif du rejet", body: () => ({ approve: false }), perm: "approvals.decide" }]} />
);

export function ReportingPage() {
  const { tenantId, can } = useTenant();
  const d = useApi<{ modules: Row[]; kpis: Record<string, number | null>; ai_usage: Row[]; schedules: Record<string, Row> }>("/reporting/global");
  const download = async (fmt: string) => {
    const res = await api<Response>(`/reporting/export.${fmt}`, { tenantId, raw: true });
    const url = URL.createObjectURL(await res.blob());
    Object.assign(document.createElement("a"), { href: url, download: `growth-ia.${fmt}` }).click();
    URL.revokeObjectURL(url);
  };
  return (
    <Stack>
      <PageHeader title="Reporting global" actions={can("reporting.export") && <Group gap={4}>{["pdf", "xlsx", "csv"].map((f) => <Button key={f} size="xs" variant="default" onClick={() => void download(f)}>{f.toUpperCase()}</Button>)}</Group>} />
      <SimpleGrid cols={{ base: 2, md: 4, lg: 6 }}>{Object.entries(d.data?.kpis ?? {}).map(([k, v]) => <Card key={k} withBorder><Text size="xs" c="dimmed">{k}</Text><Title order={4}>{v ?? "—"}</Title></Card>)}</SimpleGrid>
      <Table striped><Table.Thead><Table.Tr><Table.Th>Module</Table.Th><Table.Th>Dernière exécution</Table.Th><Table.Th>Statut</Table.Th><Table.Th>Durée</Table.Th><Table.Th>Exécutions</Table.Th><Table.Th>Erreurs</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>{d.data?.modules.map((m) => { const l = m.last_execution as Row | null; return (
          <Table.Tr key={String(m.module)}><Table.Td>{String(m.module)}</Table.Td><Table.Td>{formatDate(l?.created_at as string)}</Table.Td><Table.Td><StatusBadge value={(l?.status as string) ?? "unknown"} /></Table.Td>
            <Table.Td>{l?.duration_ms ? `${String(l.duration_ms)} ms` : "—"}</Table.Td><Table.Td>{String(m.executions)}</Table.Td><Table.Td>{String(m.errors)}</Table.Td></Table.Tr>); })}</Table.Tbody></Table>
      <DataTable rows={d.data?.ai_usage.map((a): Row => ({ ...a, id: String(a.feature_code) }))} columns={[{ key: "feature_code", label: "Fonctionnalité IA" }, { key: "calls", label: "Appels" }, { key: "input_tokens", label: "Tokens in" }, { key: "output_tokens", label: "Tokens out" }, { key: "cost_cents", label: "Coût (cts)" }]} />
    </Stack>
  );
}

export function ConnectorsV2Page() {
  const { tenantId, can } = useTenant();
  const qc = useQueryClient();
  const st = useApi<Row[]>("/connectors/status");
  const cat = useApi<Row[]>("/connectors");
  const [form, setForm] = useState<{ id: string; type: string; secrets: string; settings: string } | null>(null);
  const call = useMutation({ mutationFn: ({ path, body }: { path: string; body?: unknown }) => api<Row>(path, { method: "POST", body: body ?? {}, tenantId }),
    onSuccess: (r) => { notifications.show({ message: JSON.stringify(r) }); if (r.authorization_url) window.location.href = String(r.authorization_url); void qc.invalidateQueries({ queryKey: ["/connectors/status"] }); } });
  return (
    <Stack>
      <PageHeader title="Connecteurs" subtitle="Not configured → Configured → Authorized → Connected → Tested · aucun succès simulé" />
      <DataTable rows={st.data} loading={st.isLoading} error={st.error} columns={[{ key: "provider_name", label: "Fournisseur" }, { key: "display_name", label: "Compte" },
        statusCol(), dateCol("last_test_at", "Dernier test"), { key: "last_error", label: "Erreur" }, { key: "credential_hint", label: "Secret" },
        { key: "a", label: "", render: (r) => can("connectors.manage") && <Group gap={4}>
          <Button size="compact-xs" variant="light" onClick={() => setForm({ id: r.id, type: "api_key", secrets: "{}", settings: JSON.stringify(r.settings ?? {}) })}>Secrets</Button>
          <Button size="compact-xs" variant="light" onClick={() => call.mutate({ path: `/connector-accounts/${r.id}/oauth/start` })}>OAuth</Button>
          <Button size="compact-xs" onClick={() => call.mutate({ path: `/connector-accounts/${r.id}/test` })}>Tester</Button>
          <Button size="compact-xs" variant="default" onClick={() => call.mutate({ path: `/connector-accounts/${r.id}/disconnect` })}>Déconnecter</Button></Group> }]} />
      {form && <Card withBorder><Stack gap={4}><Title order={6}>Secrets (chiffrés côté serveur, jamais réaffichés)</Title>
        <Select data={["api_key", "basic", "webhook_secret", "oauth_token"]} value={form.type} onChange={(v) => setForm({ ...form, type: v ?? "api_key" })} />
        <Textarea label='Secrets JSON (ex {"api_key":"…"} / {"username":"…","password":"…"})' value={form.secrets} onChange={(e) => setForm({ ...form, secrets: e.currentTarget.value })} />
        <Textarea label='Paramètres non secrets JSON (site_url, host, domain, phone_number_id…)' value={form.settings} onChange={(e) => setForm({ ...form, settings: e.currentTarget.value })} />
        <Group><Button size="xs" onClick={() => { call.mutate({ path: `/connector-accounts/${form.id}/credentials`, body: { credential_type: form.type, secrets: JSON.parse(form.secrets), settings: JSON.parse(form.settings) } }); setForm(null); }}>Enregistrer</Button>
          <Button size="xs" variant="default" onClick={() => setForm(null)}>Annuler</Button></Group></Stack></Card>}
      <ModulePage title="Ajouter un compte" endpoint="/connector-accounts" module="integrations" writePerm="connectors.manage" columns={[{ key: "display_name", label: "Compte" }, statusCol()]}
        fields={[{ name: "provider", label: "Fournisseur", type: "select", options: (cat.data ?? []).map((c) => ({ value: String(c.id), label: `${String(c.name)} (${String(c.authorization_status)})` })) }, { name: "display_name", label: "Nom", required: true }, { name: "product", label: "Produit (id)" }]} />
    </Stack>
  );
}
