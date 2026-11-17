import { Alert, Button, Card, Group, Modal, NumberInput, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { HistoryCentre } from "@/features/HistoryCentre";
import { api } from "@/services/api";
import type { HealthCheck, Paged } from "@/types/api";
import { formatDate } from "@/utils/format";

type Row = Record<string, unknown> & { id: string };
const PLANS = ["DEMO", "STARTER", "GROWTH", "GROWTH_ENTREPRISE"];

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
  const [form, setForm] = useState({ name: "", slug: "", plan_code: "STARTER", owner_user_id: "" });
  const q = useQuery({ queryKey: ["pilot-tenants", search], queryFn: () => api<Paged<Row>>("/pilot/tenants", { query: { search } }) });
  const create = useMutation({
    mutationFn: () => api("/pilot/tenants", { method: "POST", body: { ...form, owner_user_id: form.owner_user_id || null } }),
    onSuccess: () => { close(); void qc.invalidateQueries({ queryKey: ["pilot-tenants"] }); },
  });
  return (
    <>
      <PageHeader title={t("nav.tenants")} actions={<Group><TextInput placeholder={t("app.search")} value={search} onChange={(e) => setSearch(e.currentTarget.value)} /><Button onClick={open}>{t("pilot.newTenant")}</Button></Group>} />
      <DataTable rows={q.data?.results} loading={q.isLoading} error={q.error} onRowClick={(r) => navigate(`/pilot/tenants/${r.id}`)} columns={[
        { key: "name", label: "Nom" }, { key: "slug", label: "Slug" }, { key: "status", label: "Statut", render: (r) => <StatusBadge value={r.status as string} /> },
        { key: "is_demo", label: "DEMO", render: (r) => (r.is_demo ? "✓" : "") }, { key: "created_at", label: "Créé", render: (r) => formatDate(r.created_at as string) }]} />
      <Modal opened={opened} onClose={close} title={t("pilot.newTenant")}>
        <Stack>
          <TextInput label="Nom" value={form.name} onChange={(e) => setForm({ ...form, name: e.currentTarget.value })} />
          <TextInput label="Slug" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.currentTarget.value })} />
          <TextInput label="Owner user id (optionnel)" value={form.owner_user_id} onChange={(e) => setForm({ ...form, owner_user_id: e.currentTarget.value })} />
          <Select label={t("license.plan")} data={PLANS} value={form.plan_code} onChange={(v) => setForm({ ...form, plan_code: v ?? "STARTER" })} />
          <Button onClick={() => create.mutate()} loading={create.isPending}>{t("app.create")}</Button>
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
  return (
    <>
      <PageHeader title={(s?.name as string) ?? ""} subtitle={s?.slug as string} actions={s && (s.status === "suspended"
        ? <Button color="green" onClick={() => status.mutate("reactivate")}>{t("pilot.reactivate")}</Button>
        : <Button color="red" onClick={() => status.mutate("suspend")}>{t("pilot.suspend")}</Button>)} />
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
