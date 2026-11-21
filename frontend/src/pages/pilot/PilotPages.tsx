import { Alert, Badge, Button, Card, Group, Modal, NumberInput, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { HistoryCentre } from "@/features/HistoryCentre";
import { api, ApiError } from "@/services/api";
import type { HealthCheck, Paged } from "@/types/api";
import { formatDate } from "@/utils/format";
import { PilotOAuthClientsCard } from "@/pages/tenant/ConnectorsPage";
import { PilotLicenseAllocations, UsersManager } from "@/pages/tenant/UsersPage";

type Row = Record<string, unknown> & { id: string };

/** Opens a tenant workspace as PILOTE: grants full access server-side (audited), refreshes /me, then navigates. */
function useEnterTenant() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<{ tenant_id: string }>(`/pilot/tenants/${id}/enter`, { method: "POST", body: {} }),
    onSuccess: async (r) => { await qc.invalidateQueries({ queryKey: ["me"] }); navigate(`/t/${r.tenant_id}/dashboard`); },
  });
}
const PLANS = [
  { value: "OFFRE_STARTER", label: "Starter — 20 € / mois" }, { value: "OFFRE_PRO", label: "Pro — 50 € / mois" },
  { value: "OFFRE_PROFESSIONNELLE", label: "Professionnelle — 200 € / mois" }, { value: "DEMO", label: "Essai gratuit" },
  { value: "STARTER", label: "STARTER (ancien)" }, { value: "GROWTH", label: "GROWTH (ancien)" }, { value: "GROWTH_ENTREPRISE", label: "GROWTH_ENTREPRISE (ancien)" },
];
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** "Café Dupont & Fils" -> "cafe-dupont-fils" : seuls a-z, 0-9 et "-" sont acceptés par l'API. */
const slugify = (v: string): string =>
  v.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 63);

/** Turns an API validation error into one readable line per field. */
const apiErrorText = (e: unknown): string => {
  if (!(e instanceof ApiError)) return String((e as Error)?.message ?? e);
  const fields = Object.entries(e.details ?? {}).map(([k, v]) => `${k} : ${Array.isArray(v) ? v.join(" ") : String(v)}`);
  return fields.length ? fields.join(" — ") : e.message;
};

export function PilotOverviewPage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["pilot-overview"], queryFn: () => api<{ tenants: Record<string, number> }>("/pilot/overview") });
  const h = useQuery({ queryKey: ["pilot-health"], queryFn: () => api<{ overall: string }>("/pilot/health") });
  return (
    <>
      <PageHeader title={t("nav.pilot")} />
      <SimpleGrid cols={{ base: 2, md: 5 }}>
        {Object.entries(q.data?.tenants ?? {}).map(([k, v]) => <Card key={k} withBorder><Text size="xs" c="dimmed" tt="uppercase">{k}</Text><Title order={3}>{v}</Title></Card>)}
        <Card withBorder><Text size="xs" c="dimmed">{t("health.overall")}</Text><StatusBadge value={h.data?.overall} /></Card>
      </SimpleGrid>
    </>
  );
}

export function PilotTenantsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [opened, { open, close }] = useDisclosure(false);
  const [form, setForm] = useState({ name: "", slug: "", plan_code: "OFFRE_STARTER", owner_user_id: "" });
  const [slugTouched, setSlugTouched] = useState(false);
  const owner = form.owner_user_id.trim();
  const ownerInvalid = owner !== "" && !UUID_RE.test(owner);
  const canCreate = form.name.trim() !== "" && form.slug !== "" && !ownerInvalid;
  const q = useQuery({ queryKey: ["pilot-tenants", search], queryFn: () => api<Paged<Row>>("/pilot/tenants", { query: { search } }) });
  const enter = useEnterTenant();
  const create = useMutation({
    mutationFn: () => api<Row>("/pilot/tenants", { method: "POST", body: { ...form, name: form.name.trim(), slug: slugify(form.slug), owner_user_id: owner || null } }),
    onSuccess: (r) => { close(); navigate(`/pilot/tenants/${r.id}`); setForm({ name: "", slug: "", plan_code: "OFFRE_STARTER", owner_user_id: "" }); setSlugTouched(false); void qc.invalidateQueries({ queryKey: ["pilot-tenants"] }); },
  });
  return (
    <>
      <PageHeader title={t("nav.tenants")} actions={<Group><TextInput placeholder={t("app.search")} value={search} onChange={(e) => setSearch(e.currentTarget.value)} /><Button onClick={open}>{t("pilot.newTenant")}</Button></Group>} />
      <DataTable rows={q.data?.results} loading={q.isLoading} error={q.error} onRowClick={(r) => navigate(`/pilot/tenants/${r.id}`)} columns={[
        { key: "name", label: "Nom" }, { key: "slug", label: "Slug" }, { key: "status", label: "Statut", render: (r) => <StatusBadge value={r.status as string} /> },
        { key: "is_demo", label: "DEMO", render: (r) => (r.is_demo ? "✓" : "") }, { key: "created_at", label: "Créé", render: (r) => formatDate(r.created_at as string) },
        { key: "open", label: "", render: (r) => r.status === "active" && (
          <Button size="xs" variant="light" loading={enter.isPending && enter.variables === r.id}
            onClick={(e) => { e.stopPropagation(); enter.mutate(r.id); }}>Ouvrir l'espace</Button>) }]} />
      <Modal opened={opened} onClose={close} title={t("pilot.newTenant")}>
        <Stack>
          <TextInput label="Nom" required value={form.name}
            onChange={(e) => { const name = e.currentTarget.value; setForm({ ...form, name, slug: slugTouched ? form.slug : slugify(name) }); }} />
          <TextInput label="Slug" required description="Généré depuis le nom : minuscules, chiffres et tirets uniquement" value={form.slug}
            onChange={(e) => { setSlugTouched(true); setForm({ ...form, slug: slugify(e.currentTarget.value) }); }} />
          <TextInput label="Owner user id (optionnel)" description="Identifiant (UUID) d'un utilisateur existant, ou laisser vide"
            value={form.owner_user_id} error={ownerInvalid ? "Format attendu : xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" : undefined}
            onChange={(e) => setForm({ ...form, owner_user_id: e.currentTarget.value })} />
          <Select label={t("license.plan")} data={PLANS} value={form.plan_code} onChange={(v) => setForm({ ...form, plan_code: v ?? "OFFRE_STARTER" })} />
          {create.isError && <Alert color="red">{apiErrorText(create.error)}</Alert>}
          <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!canCreate}>{t("app.create")}</Button>
        </Stack>
      </Modal>
    </>
  );
}

interface License { subscription: Row | null; quotas: { quota_code: string; effective_limit: number | null; used: number | null }[]; modules: { code: string; status: string }[] }

export function PilotTenantDetailPage() {
  const { t } = useTranslation();
  const { tenantId = "" } = useParams();
  const qc = useQueryClient();
  const tenant = useQuery({ queryKey: ["pilot-tenant", tenantId], queryFn: () => api<Row>(`/pilot/tenants/${tenantId}`) });
  const lic = useQuery({ queryKey: ["pilot-license", tenantId], queryFn: () => api<License>(`/pilot/tenants/${tenantId}/license`) });
  const conn = useQuery({ queryKey: ["pilot-conn", tenantId], queryFn: () => api<Row[]>(`/pilot/tenants/${tenantId}/connectors`) });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["pilot-tenant", tenantId] }); void qc.invalidateQueries({ queryKey: ["pilot-license", tenantId] }); void qc.invalidateQueries({ queryKey: ["pilot-conn", tenantId] }); };
  const ask = (label: string) => window.prompt(`${label} — ${t("app.reason")}`) ?? "";
  const status = useMutation({ mutationFn: (op: "suspend" | "reactivate") => api(`/pilot/tenants/${tenantId}/${op}`, { method: "POST", body: { reason: ask(op) } }), onSuccess: refresh });
  const license = useMutation({ mutationFn: (body: Record<string, unknown>) => api(`/pilot/tenants/${tenantId}/license`, { method: "POST", body }), onSuccess: refresh });
  const connector = useMutation({ mutationFn: (body: Record<string, unknown>) => api(`/pilot/tenants/${tenantId}/connectors`, { method: "POST", body }), onSuccess: refresh });
  const [plan, setPlan] = useState<string | null>(null);
  const [quota, setQuota] = useState<{ code: string | null; limit: number | string }>({ code: null, limit: "" });
  const [module, setModule] = useState("");
  const s = tenant.data;
  const enter = useEnterTenant();
  return (
    <>
      <PageHeader title={(s?.name as string) ?? ""} subtitle={s?.slug as string} actions={s && (s.status === "suspended"
        ? <Button color="green" onClick={() => status.mutate("reactivate")}>{t("pilot.reactivate")}</Button>
        : <Group>
            <Button onClick={() => enter.mutate(tenantId)} loading={enter.isPending}>Ouvrir l'espace du tenant</Button>
            <Button color="red" variant="light" onClick={() => status.mutate("suspend")}>{t("pilot.suspend")}</Button>
          </Group>)} />
      {s?.status !== "suspended" && <Alert color="blue" mb="md">
        « Ouvrir l'espace du tenant » vous donne un accès complet à ce tenant (tracé dans l'audit) : utilisateurs et invitations,
        scheduler SEO / GEO / Smart Prospect, produits, sites, connecteurs, paramètres…
      </Alert>}
      {s?.status === "suspended" && <Alert color="red" mb="md">{String(s.suspended_reason ?? "")}</Alert>}
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card withBorder>
          <Title order={5} mb="sm">{t("license.plan")}: {String(lic.data?.subscription?.plan ?? "—")} <StatusBadge value={lic.data?.subscription?.status as string} /></Title>
          <Group align="flex-end" mb="md">
            <Select label={t("pilot.changePlan")} data={PLANS} value={plan} onChange={setPlan} />
            <Button disabled={!plan} onClick={() => license.mutate({ operation: "change_plan", plan_code: plan, reason: ask(t("pilot.changePlan")) })}>OK</Button>
          </Group>
          <Table><Table.Tbody>{lic.data?.quotas.map((q) => (
            <Table.Tr key={q.quota_code}><Table.Td>{q.quota_code}</Table.Td><Table.Td>{q.used ?? "—"} / {q.effective_limit ?? "∞"}</Table.Td></Table.Tr>))}</Table.Tbody></Table>
          <Group align="flex-end" mt="md">
            <Select label={t("pilot.overrideQuota")} data={lic.data?.quotas.map((q) => q.quota_code) ?? []} value={quota.code} onChange={(v) => setQuota({ ...quota, code: v })} />
            <NumberInput label={t("license.limit")} value={quota.limit} onChange={(v) => setQuota({ ...quota, limit: v })} w={110} />
            <Button disabled={!quota.code} onClick={() => license.mutate({ operation: "quota_override", quota_code: quota.code, limit: quota.limit === "" ? null : Number(quota.limit), reason: ask(t("pilot.overrideQuota")) })}>OK</Button>
          </Group>
        </Card>
        <Card withBorder>
          <Title order={5} mb="sm">{t("license.modules")}</Title>
          <Group mb="md">{lic.data?.modules.map((m) => <StatusBadge key={m.code} value={`${m.code}: ${m.status}`} />)}</Group>
          <Group align="flex-end">
            <TextInput label={t("pilot.authorizeModule")} placeholder="seo, geo, content…" value={module} onChange={(e) => setModule(e.currentTarget.value)} />
            <Button onClick={() => license.mutate({ operation: "module", module_code: module, status: "enabled", reason: ask(t("pilot.authorizeModule")) })}>Enable</Button>
            <Button variant="default" onClick={() => license.mutate({ operation: "module", module_code: module, status: "disabled", reason: ask(t("pilot.authorizeModule")) })}>Disable</Button>
          </Group>
          <Title order={5} mt="lg" mb="sm">{t("nav.connectors")}</Title>
          <DataTable rows={conn.data?.map((c): Row => ({ ...c, id: String(c.code) }))} columns={[
            { key: "name", label: "Connecteur" }, { key: "status", label: "Statut", render: (r) => <StatusBadge value={r.status as string} /> },
            { key: "a", label: "", render: (r) => <Button size="xs" variant="light" onClick={() => connector.mutate({ provider_code: r.code, status: r.status === "enabled" ? "disabled" : "enabled", reason: ask(t("pilot.authorizeConnector")) })}>{r.status === "enabled" ? "Disable" : "Enable"}</Button> }]} />
        </Card>
      </SimpleGrid>
      <Stack mt="lg" gap="lg">
        <PilotLicenseAllocations tenantId={tenantId} />
        <UsersManager tenantId={tenantId} pilot canManage />
      </Stack>
    </>
  );
}

export function PilotPlansPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["plans"], queryFn: () => api<(Row & { quotas: Record<string, number | null> })[]>("/pilot/plans") });
  const update = useMutation({
    mutationFn: (b: { plan_code: string; quota_code: string; limit: number | null }) => api("/pilot/plans", { method: "PATCH", body: { ...b, reason: "PILOTE console" } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["plans"] }),
  });
  const codes = Array.from(new Set(q.data?.flatMap((p) => Object.keys(p.quotas)) ?? [])).sort();
  return (
    <>
      <PageHeader title={t("nav.plans")} />
      <Table withTableBorder>
        <Table.Thead><Table.Tr><Table.Th>Quota</Table.Th>{q.data?.map((p) => <Table.Th key={p.id}>{String(p.code)}</Table.Th>)}</Table.Tr></Table.Thead>
        <Table.Tbody>{codes.map((c) => (
          <Table.Tr key={c}><Table.Td>{c}</Table.Td>{q.data?.map((p) => (
            <Table.Td key={p.id}><NumberInput size="xs" w={120} placeholder="∞" defaultValue={p.quotas[c] ?? ""}
              onBlur={(e) => update.mutate({ plan_code: String(p.code), quota_code: c, limit: e.currentTarget.value === "" ? null : Number(e.currentTarget.value) })} /></Table.Td>))}
          </Table.Tr>))}</Table.Tbody>
      </Table>
    </>
  );
}

export function PilotUsagePage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["usage"], queryFn: () => api<{ usage_by_tenant: Row[]; ai_cost_30d: number }>("/pilot/usage") });
  return (
    <>
      <PageHeader title={t("nav.usage")} subtitle={`IA 30j : ${((q.data?.ai_cost_30d ?? 0) / 100).toFixed(2)} €`} />
      <DataTable rows={q.data?.usage_by_tenant} loading={q.isLoading} error={q.error} columns={[{ key: "name", label: "Tenant" }, { key: "events", label: "Événements" }, { key: "cost_cents", label: "Coût (cts)" }]} />
    </>
  );
}

export const PilotHistoryPage = () => <HistoryCentre scope="pilot" />;

export function PilotErrorsPage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["errors"], queryFn: () => api<Paged<Row>>("/pilot/history/errors") });
  return (
    <>
      <PageHeader title={t("nav.errors")} />
      <DataTable rows={q.data?.results} loading={q.isLoading} error={q.error} columns={[
        { key: "created_at", label: "Date", render: (r) => formatDate(r.created_at as string) }, { key: "service_code", label: "Service" },
        { key: "error_code", label: "Code" }, { key: "message", label: "Message" }, { key: "correlation_id", label: "Correlation" }]} />
    </>
  );
}

export function SystemHealthPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["pilot-health"], queryFn: () => api<{ overall: string; checks: HealthCheck[] }>("/pilot/health"), refetchInterval: 30_000 });
  const run = useMutation({ mutationFn: () => api("/pilot/health/run", { method: "POST", body: {} }), onSuccess: () => void qc.invalidateQueries({ queryKey: ["pilot-health"] }) });
  const groups = Object.entries((q.data?.checks ?? []).reduce<Record<string, HealthCheck[]>>((acc, c) => ({ ...acc, [c.service_name]: [...(acc[c.service_name] ?? []), c] }), {}));
  return (
    <>
      <PageHeader title={t("nav.health")} actions={<Group><StatusBadge value={q.data?.overall} /><Button onClick={() => run.mutate()} loading={run.isPending}>{t("health.run")}</Button></Group>} />
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {groups.map(([name, checks]) => (
          <Card key={name} withBorder>
            <Title order={5} mb="xs">{name}</Title>
            <Stack gap="xs">{checks.map((c) => (
              <div key={c.code}>
                <Group justify="space-between"><Text size="sm">{c.name}</Text><StatusBadge value={c.status ?? "unknown"} /></Group>
                <Text size="xs" c="dimmed">{t("health.lastCheck")}: {formatDate(c.checked_at)}{c.latency_ms != null ? ` · ${c.latency_ms} ms` : ""}</Text>
                {c.error_message && <Text size="xs" c="red">{c.error_message}</Text>}
                {c.recommendation && <Text size="xs">{t("health.recommendation")}: {c.recommendation}</Text>}
              </div>))}
            </Stack>
          </Card>
        ))}
      </SimpleGrid>
    </>
  );
}

export function PilotIncidentsPage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["incidents"], queryFn: () => api<Row[]>("/pilot/incidents") });
  return (
    <>
      <PageHeader title={t("nav.incidents")} />
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} columns={[
        { key: "title", label: "Titre" }, { key: "severity", label: "Sévérité" }, { key: "status", label: "Statut", render: (r) => <StatusBadge value={r.status as string} /> },
        { key: "started_at", label: "Début", render: (r) => formatDate(r.started_at as string) }]} />
    </>
  );
}

export function PilotAIPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["pilot-ai"], queryFn: () => api<{ providers: Row[]; models: Row[]; routes: Row[]; default_model: string | null; env_keys: Record<string, boolean> }>("/pilot/ai") });
  const [quickKey, setQuickKey] = useState("");
  const op = useMutation({ mutationFn: (b: Record<string, unknown>) => api("/pilot/ai", { method: "POST", body: b }), onSuccess: () => void qc.invalidateQueries({ queryKey: ["pilot-ai"] }) });
  const [k, setK] = useState({ provider_code: "anthropic", api_key: "", base_url: "" });
  const [m, setM] = useState({ provider_code: "anthropic", model_code: "", input_cost_per_mtok_cents: "", output_cost_per_mtok_cents: "" });
  const [r, setR] = useState({ feature_code: "*", model_code: "", priority: "1" });
  return (
    <>
      <PageHeader title="Fournisseurs IA" subtitle="Clés chiffrées côté backend · coûts calculés uniquement à partir des tarifs saisis et des tokens réellement consommés" />
      {(() => {
        const def = q.data?.models.find((x) => x.code === q.data?.default_model);
        const prov = String(def?.provider ?? "anthropic");
        const stored = !!q.data?.providers.find((x) => x.code === prov)?.has_key;
        const viaEnv = !!q.data?.env_keys?.[prov];
        return (
          <Card withBorder mb="md" padding="lg">
            <Group justify="space-between" align="flex-start" wrap="wrap">
              <Stack gap={4}>
                <Title order={5}>Modèle par défaut</Title>
                <Text size="sm" c="dimmed">Utilisé par toutes les fonctionnalités sans routage spécifique (analyses, contenus, assistant SEO/GEO, THOR…).</Text>
                <Select w={340} mt="xs" value={q.data?.default_model ?? null} allowDeselect={false} placeholder="Choisir un modèle" searchable
                  data={Object.entries((q.data?.models ?? []).filter((x) => x.is_enabled).reduce<Record<string, { value: string; label: string }[]>>((acc, x) => {
                    const prov = String(x.provider);
                    (acc[prov] ??= []).push({ value: String(x.code), label: String(x.name) });
                    return acc;
                  }, {})).map(([group, items]) => ({ group, items }))}
                  onChange={(v) => v && op.mutate({ operation: "set_default", model_code: v })} />
              </Stack>
              <Stack gap={6} miw={300}>
                <Text size="sm" fw={500}>Clé {prov}</Text>
                {stored ? <Badge color="green">Enregistrée (chiffrée)</Badge> : viaEnv ? <Badge color="teal">Fournie par la variable du serveur</Badge> : <Badge color="red">Manquante : l'IA est inactive</Badge>}
                {!stored && (
                  <Group gap="xs" wrap="nowrap">
                    <TextInput flex={1} size="xs" type="password" placeholder={prov === "anthropic" ? "sk-ant-…" : "clé API"} value={quickKey} onChange={(e) => setQuickKey(e.currentTarget.value)} />
                    <Button size="xs" disabled={quickKey.length < 10} onClick={() => { op.mutate({ operation: "set_key", provider_code: prov, api_key: quickKey }); setQuickKey(""); }}>Enregistrer</Button>
                  </Group>
                )}
                <Text size="xs" c="dimmed">Les tarifs ne sont pas présumés : saisissez-les ci-dessous pour le calcul des coûts.</Text>
              </Stack>
            </Group>
          </Card>
        );
      })()}
      <DataTable rows={q.data?.providers.map((p): Row => ({ ...p, id: String(p.code) }))} columns={[{ key: "name", label: "Fournisseur" }, { key: "api_style", label: "API" },
        { key: "has_key", label: "Clé", render: (x) => (x.has_key ? "✓" : "—") }, { key: "base_url", label: "URL" }, { key: "priority", label: "Priorité" }]} />
      <SimpleGrid cols={{ base: 1, lg: 3 }} mt="md">
        <Card withBorder><Stack gap={4}><Title order={6}>Clé API</Title>
          <Select data={(q.data?.providers ?? []).map((p) => String(p.code))} value={k.provider_code} onChange={(v) => setK({ ...k, provider_code: v ?? "" })} />
          <TextInput placeholder="api key" type="password" value={k.api_key} onChange={(e) => setK({ ...k, api_key: e.currentTarget.value })} />
          <TextInput placeholder="base URL (optionnel)" value={k.base_url} onChange={(e) => setK({ ...k, base_url: e.currentTarget.value })} />
          <Button size="xs" onClick={() => { op.mutate({ operation: "set_key", ...k }); setK({ ...k, api_key: "" }); }}>Enregistrer</Button></Stack></Card>
        <Card withBorder><Stack gap={4}><Title order={6}>Modèle & tarifs (cts / M tokens)</Title>
          <Select data={(q.data?.providers ?? []).map((p) => String(p.code))} value={m.provider_code} onChange={(v) => setM({ ...m, provider_code: v ?? "" })} />
          <TextInput placeholder="code modèle exact" value={m.model_code} onChange={(e) => setM({ ...m, model_code: e.currentTarget.value })} />
          <TextInput placeholder="prix input" value={m.input_cost_per_mtok_cents} onChange={(e) => setM({ ...m, input_cost_per_mtok_cents: e.currentTarget.value })} />
          <TextInput placeholder="prix output" value={m.output_cost_per_mtok_cents} onChange={(e) => setM({ ...m, output_cost_per_mtok_cents: e.currentTarget.value })} />
          <Button size="xs" onClick={() => op.mutate({ operation: "upsert_model", ...m, input_cost_per_mtok_cents: m.input_cost_per_mtok_cents || null, output_cost_per_mtok_cents: m.output_cost_per_mtok_cents || null })}>Enregistrer</Button></Stack></Card>
        <Card withBorder><Stack gap={4}><Title order={6}>Routage par fonctionnalité (fallback = priorité)</Title>
          <TextInput placeholder="feature (*, content.generate, email.classify, thor.chat, geo.engine.openai…)" value={r.feature_code} onChange={(e) => setR({ ...r, feature_code: e.currentTarget.value })} />
          <Select data={(q.data?.models ?? []).map((x) => String(x.code))} value={r.model_code} onChange={(v) => setR({ ...r, model_code: v ?? "" })} />
          <TextInput placeholder="priorité" value={r.priority} onChange={(e) => setR({ ...r, priority: e.currentTarget.value })} />
          <Button size="xs" onClick={() => op.mutate({ operation: "route", ...r })}>Ajouter</Button></Stack></Card>
      </SimpleGrid>
      <DataTable rows={q.data?.routes} columns={[{ key: "feature_code", label: "Fonctionnalité" }, { key: "model", label: "Modèle" }, { key: "priority", label: "Priorité" }, { key: "is_enabled", label: "Actif", render: (x) => (x.is_enabled ? "✓" : "—") }]} />
    </>
  );
}

export function PilotGlobalPage() {
  const q = useQuery({ queryKey: ["pilot-global"], queryFn: () => api<{ users: Row[]; schedulers: Row[]; ai_costs: Row[]; approvals_pending: Row[] }>("/pilot/global") });
  return (
    <>
      <PageHeader title="Vue globale" />
      <Title order={5}>Utilisateurs</Title>
      <DataTable rows={q.data?.users} loading={q.isLoading} error={q.error} columns={[{ key: "email", label: "E-mail" }, { key: "platform_role_code", label: "Rôle plateforme" }, { key: "tenants", label: "Tenants" }, { key: "status", label: "Statut", render: (r) => <StatusBadge value={r.status as string} /> }]} />
      <Title order={5} mt="md">Coûts IA (30 j)</Title>
      <DataTable rows={q.data?.ai_costs.map((x, i): Row => ({ ...x, id: String(i) }))} columns={[{ key: "tenant", label: "Tenant" }, { key: "provider_code", label: "Fournisseur" }, { key: "model_code", label: "Modèle" }, { key: "calls", label: "Appels" }, { key: "cost_cents", label: "Coût (cts)" }]} />
      <Title order={5} mt="md">Programmations</Title>
      <DataTable rows={q.data?.schedulers.map((x, i): Row => ({ ...x, id: String(i) }))} columns={[{ key: "tenant", label: "Tenant" }, { key: "category", label: "Catégorie" }, { key: "n", label: "Nombre" }, { key: "failing", label: "En échec" }]} />
    </>
  );
}

export function PilotConnectorsPage() {
  return (
    <>
      <PageHeader title="Connecteurs OAuth" subtitle="Enregistrez les applications OAuth (Google, GitHub, Microsoft, LinkedIn…) pour que les tenants connectent leurs comptes en un clic." />
      <PilotOAuthClientsCard />
    </>
  );
}
