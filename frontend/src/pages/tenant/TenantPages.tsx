import { Alert, Button, Card, Group, Progress, Select, SimpleGrid, Stack, Text, TextInput, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ResourcePage } from "@/components/ResourcePage";
import { StatusBadge } from "@/components/StatusBadge";
import { useMe, useTenant } from "@/hooks/useMe";
import { api } from "@/services/api";
import { formatDate } from "@/utils/format";

type Row = Record<string, unknown> & { id: string };

export function DashboardPage() {
  const { t } = useTranslation();
  const { tenantId, tenant } = useTenant();
  const q = useQuery({ queryKey: ["dashboard", tenantId], queryFn: () => api<{ counts: Record<string, number>; activity_30d: { day: string; events: number }[] }>("/dashboard", { tenantId }) });
  return (
    <>
      <PageHeader title={tenant?.name ?? ""} subtitle={tenant?.subscription ? `${tenant.subscription.plan} · ${tenant.subscription.status}` : undefined} />
      {tenant?.subscription?.status === "trialing" && tenant.subscription.trial_ends_at && (
        <Alert mb="md" color="blue">{t("license.trialEnds")}: {formatDate(tenant.subscription.trial_ends_at)}</Alert>
      )}
      <SimpleGrid cols={{ base: 2, md: 3, lg: 6 }}>
        {Object.entries(q.data?.counts ?? {}).map(([k, v]) => (
          <Card key={k} withBorder><Text size="xs" c="dimmed" tt="uppercase">{k.replace(/_/g, " ")}</Text><Title order={3}>{v}</Title></Card>
        ))}
      </SimpleGrid>
    </>
  );
}

export const ProductsPage = () => {
  const { t } = useTranslation();
  return (
    <ResourcePage<Row> title={t("nav.products")} endpoint="/products" writePerm="products.write"
      columns={[{ key: "name", label: "Nom" }, { key: "slug", label: "Slug" }, { key: "status", label: "Statut", render: (r) => <StatusBadge value={r.status as string} /> },
        { key: "version_number", label: "v" }, { key: "updated_at", label: "MAJ", render: (r) => formatDate(r.updated_at as string) }]}
      fields={[{ name: "name", label: "Nom", required: true }, { name: "slug", label: "Slug", required: true }, { name: "description", label: "Description", multiline: true }]} />
  );
};

export const WebsitesPage = () => {
  const { t } = useTranslation();
  return (
    <ResourcePage<Row> title={t("nav.websites")} endpoint="/websites" writePerm="websites.write"
      columns={[{ key: "url", label: "URL" }, { key: "name", label: "Nom" }, { key: "status", label: "Statut", render: (r) => <StatusBadge value={r.status as string} /> }]}
      fields={[{ name: "url", label: "URL", required: true }, { name: "name", label: "Nom" }]} />
  );
};

export function SchedulerPage() {
  const { t } = useTranslation();
  const { tenantId } = useTenant();
  const runs = useQuery({ queryKey: ["runs", tenantId], queryFn: () => api<Row[]>("/scheduler-runs", { tenantId }) });
  return (
    <Stack>
      <ResourcePage<Row> title={t("nav.scheduler")} endpoint="/schedulers" writePerm="scheduler.manage"
        columns={[{ key: "name", label: "Nom" }, { key: "timezone", label: "TZ" }, { key: "status", label: "Statut", render: (r) => <StatusBadge value={r.status as string} /> }]}
        fields={[{ name: "name", label: "Nom", required: true }, { name: "description", label: "Description", multiline: true }]} />
      <Title order={4}>{t("history.executions")}</Title>
      <DataTable rows={runs.data} loading={runs.isLoading} error={runs.error} columns={[
        { key: "task_name", label: "Tâche" }, { key: "status", label: "Statut", render: (r) => <StatusBadge value={r.status as string} /> },
        { key: "duration_ms", label: "ms" }, { key: "started_at", label: "Début", render: (r) => formatDate(r.started_at as string) }]} />
    </Stack>
  );
}

export function ConnectorsPage() {
  const { t } = useTranslation();
  const { tenantId } = useTenant();
  const q = useQuery({ queryKey: ["connectors", tenantId], queryFn: () => api<Row[]>("/connectors", { tenantId }) });
  return (
    <>
      <PageHeader title={t("nav.connectors")} />
      <DataTable rows={q.data?.map((r): Row => ({ ...r, id: String(r.code) }))} loading={q.isLoading} error={q.error} columns={[
        { key: "name", label: "Connecteur" }, { key: "category", label: "Catégorie" }, { key: "auth_type", label: "Auth" },
        { key: "authorization_status", label: "Autorisation", render: (r) => <StatusBadge value={r.authorization_status as string} /> }]} />
    </>
  );
}

export function MembersPage() {
  const { t } = useTranslation();
  const { tenantId, can } = useTenant();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["members", tenantId], queryFn: () => api<Row[]>("/members", { tenantId }) });
  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) => api(`/members/${id}`, { method: "PUT", body: { role_code: role, reason: "UI" }, tenantId }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["members", tenantId] }),
  });
  return (
    <>
      <PageHeader title={t("nav.members")} />
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} columns={[
        { key: "display_name", label: "Nom" }, { key: "email", label: "E-mail" }, { key: "status", label: "Statut", render: (r) => <StatusBadge value={r.status as string} /> },
        { key: "roles", label: "Rôle", render: (r) => {
          const roles = (r.roles as string[]) ?? [];
          if (!can("members.manage") || roles.includes("tenant_owner")) return roles.join(", ");
          return <Select size="xs" value={roles[0] ?? null} data={["tenant_admin", "tenant_member", "tenant_viewer"]} onChange={(v) => v && setRole.mutate({ id: r.id, role: v })} />;
        } }]} />
    </>
  );
}

const INVITE_ROLES = [
  { value: "tenant_admin", label: "Administrateur" }, { value: "tenant_manager", label: "Responsable du tenant" },
  { value: "marketing_manager", label: "Responsable marketing" }, { value: "seo_manager", label: "Responsable SEO" },
  { value: "content_manager", label: "Responsable contenu" }, { value: "social_media_manager", label: "Community manager" },
  { value: "sales_manager", label: "Responsable commercial" }, { value: "sales_rep", label: "Commercial" },
  { value: "analyst", label: "Analyste" }, { value: "tenant_member", label: "Membre" }, { value: "tenant_viewer", label: "Lecteur" },
];
const ROLE_LABEL: Record<string, string> = Object.fromEntries(INVITE_ROLES.map((r) => [r.value, r.label]));

export function InvitationsPage() {
  const { t } = useTranslation();
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string | null>("tenant_member");
  const q = useQuery({ queryKey: ["invitations", tenantId], queryFn: () => api<Row[]>("/invitations", { tenantId }) });
  const [link, setLink] = useState<string | null>(null);
  const inv = useMutation({
    mutationFn: () => api<{ accept_path?: string }>("/invitations", { method: "POST", body: { email, role_code: role }, tenantId }),
    onSuccess: (r) => { setLink(r.accept_path ? `${window.location.origin}${r.accept_path}` : null); setEmail(""); void qc.invalidateQueries({ queryKey: ["invitations", tenantId] }); },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/invitations/${id}/revoke`, { method: "POST", body: { reason: "UI" }, tenantId }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invitations", tenantId] }),
  });
  return (
    <>
      <PageHeader title={t("nav.invitations")} />
      <Group mb="md" align="flex-end">
        <TextInput label={t("auth.email")} value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
        <Select label="Profil" value={role} onChange={setRole} w={240} data={INVITE_ROLES} />
        <Button onClick={() => inv.mutate()} loading={inv.isPending} disabled={!email}>{t("app.create")}</Button>
      </Group>
      {link && <Alert color="green" mb="md" withCloseButton onClose={() => setLink(null)} title="Invitation créée">
        Aucun serveur d'e-mail n'est configuré : transmettez ce lien à la personne invitée (valable une seule fois). Elle crée son
        compte avec cette adresse e-mail et choisit elle-même son mot de passe.
        <Group mt="xs"><TextInput readOnly value={link} style={{ flex: 1 }} onFocus={(e) => e.currentTarget.select()} />
          <Button variant="light" onClick={() => void navigator.clipboard?.writeText(link)}>Copier</Button></Group>
      </Alert>}
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} columns={[
        { key: "email", label: "E-mail" }, { key: "role", label: "Profil", render: (r) => ROLE_LABEL[r.role as string] ?? String(r.role) }, { key: "status", label: "Statut", render: (r) => <StatusBadge value={r.status as string} /> },
        { key: "expires_at", label: "Expire", render: (r) => formatDate(r.expires_at as string) },
        { key: "a", label: "", render: (r) => r.status === "pending" && <Button size="xs" variant="subtle" color="red" onClick={() => revoke.mutate(r.id)}>Révoquer</Button> }]} />
    </>
  );
}

interface License { subscription: Row | null; quotas: { quota_code: string; effective_limit: number | null; used: number | null }[]; modules: { code: string; name: string; status: string }[] }

interface Offer { code: string; name: string; description: string | null; price_monthly_cents: number; currency: string }

function Offers({ tenantId, current }: { tenantId: string; current?: string }) {
  const catalog = useQuery({ queryKey: ["billing-plans"], queryFn: () => api<{ plans: Offer[]; online_payment: boolean }>("/billing/plans") });
  const back = new URLSearchParams(window.location.search).get("checkout");
  const pay = useMutation({
    mutationFn: (plan_code: string) => api<{ url: string }>("/billing/checkout", { method: "POST", body: { plan_code }, tenantId }),
    onSuccess: (r) => { if (r.url) window.location.href = r.url; },
  });
  const eur = (c: number) => (c / 100).toLocaleString("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
  return (
    <>
      {back === "success" && <Alert color="green" mb="md">Paiement reçu : votre abonnement est activé (quelques secondes peuvent être nécessaires).</Alert>}
      {back === "cancel" && <Alert color="gray" mb="md">Paiement annulé : aucun montant n'a été débité.</Alert>}
      {catalog.data && !catalog.data.online_payment && <Alert color="yellow" mb="md">Le paiement en ligne sera bientôt disponible.</Alert>}
      {pay.isError && <Alert color="red" mb="md">{(pay.error as Error).message}</Alert>}
      <SimpleGrid cols={{ base: 1, md: 3 }} mb="lg">
        {catalog.data?.plans.map((p) => (
          <Card key={p.code} withBorder padding="lg" style={current === p.code ? { borderColor: "var(--mantine-color-indigo-6)", borderWidth: 2 } : undefined}>
            <Title order={4}>{p.name}</Title>
            <Text size="xl" fw={700} mt="xs">{eur(p.price_monthly_cents)} <Text span size="sm" c="dimmed">TTC / mois</Text></Text>
            <Text size="sm" c="dimmed" mt="xs" mb="md">Sans engagement, résiliable à tout moment.</Text>
            <Button fullWidth disabled={current === p.code || !catalog.data?.online_payment} loading={pay.isPending && pay.variables === p.code}
              onClick={() => pay.mutate(p.code)}>{current === p.code ? "Offre actuelle" : "Choisir cette offre"}</Button>
          </Card>
        ))}
      </SimpleGrid>
    </>
  );
}

export function SubscriptionPage() {
  const { t } = useTranslation();
  const { tenantId } = useTenant();
  const q = useQuery({ queryKey: ["license", tenantId], queryFn: () => api<License>("/license", { tenantId }) });
  const s = q.data?.subscription;
  return (
    <>
      <PageHeader title={t("nav.subscription")} />
      <Offers tenantId={tenantId} current={s?.plan as string | undefined} />
      {s && <Card withBorder mb="md"><Group><Text fw={600}>{String(s.plan_name)}</Text><StatusBadge value={s.status as string} />
        {s.trial_ends_at ? <Text size="sm">{t("license.trialEnds")}: {formatDate(s.trial_ends_at as string)}</Text> : null}</Group></Card>}
      <Title order={4} mb="sm">{t("license.quotas")}</Title>
      <SimpleGrid cols={{ base: 1, md: 3 }} mb="lg">
        {q.data?.quotas.map((x) => (
          <Card key={x.quota_code} withBorder>
            <Text size="sm">{x.quota_code}</Text>
            <Text size="xs" c="dimmed">{x.used ?? "—"} / {x.effective_limit ?? t("license.unlimited")}</Text>
            {x.effective_limit ? <Progress value={Math.min(100, ((x.used ?? 0) / x.effective_limit) * 100)} mt="xs" /> : null}
          </Card>
        ))}
      </SimpleGrid>
      <Title order={4} mb="sm">{t("license.modules")}</Title>
      <Group>{q.data?.modules.map((m) => <StatusBadge key={m.code} value={`${m.code}: ${m.status}`} />)}</Group>
    </>
  );
}

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const { data } = useMe();
  const qc = useQueryClient();
  const [name, setName] = useState(data?.profile?.full_name ?? "");
  const [username, setUsername] = useState(data?.profile?.username ?? "");
  const m = useMutation({
    mutationFn: () => api("/me", { method: "PATCH", body: {
      full_name: name, username: username.trim().toLowerCase() || null, locale: i18n.language, version_number: data?.profile?.version_number,
    } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["me"] }),
  });
  const err = m.error as (Error & { code?: string }) | null;
  return (
    <>
      <PageHeader title={t("nav.settings")} />
      <Stack maw={420}>
        <TextInput label={t("onboarding.fullName")} value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <TextInput label={t("auth.username")} description={t("auth.usernameHelp")} value={username}
          onChange={(e) => setUsername(e.currentTarget.value)}
          error={err ? (err.code === "username_taken" ? t("auth.usernameTaken") : err.message) : undefined} />
        <Button onClick={() => m.mutate()} loading={m.isPending}>{t("app.save")}</Button>
      </Stack>
    </>
  );
}
