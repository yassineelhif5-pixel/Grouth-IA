import {
  Alert, Anchor, Badge, Button, Card, Group, List, Modal, PasswordInput, SimpleGrid, Stack, Text, TextInput, ThemeIcon, Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconCheck, IconExternalLink, IconKey, IconPlugConnected, IconRefresh, IconX } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { RobotLoader } from "@/components/RobotLoader";
import { useTenant } from "@/hooks/useMe";
import { api, ApiError } from "@/services/api";

interface Field { name: string; label: string; secret: boolean; type: string; required: boolean; help: string; placeholder: string }
interface Account { id: string; status: string; last_test_at: string | null; last_error: string | null; settings: Record<string, string> | null; credential_hint: string | null }
interface Provider {
  code: string; name: string; category: string; method: "oauth" | "api_key" | "oauth_or_key" | "unsupported";
  oauth_available: boolean; oauth_family: string | null; family_label: string | null; authorization_status: string;
  fields: Field[]; settings_fields: Field[]; help_url: string | null; account: Account | null;
}
interface Catalog { providers: Provider[]; redirect_uri: string; note: string }

const CATEGORIES: Record<string, string> = {
  seo: "SEO", analytics: "Analytics", cms: "Sites & CMS", social: "Réseaux sociaux", email: "E-mail", messaging: "Messagerie",
  crm: "CRM", payments: "Paiements", storage: "Stockage", other: "Autres",
};
const err = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

function AccountState({ a }: { a: Account }) {
  const map: Record<string, [string, string]> = {
    tested: ["signal", "Connecté et testé"], connected: ["signal", "Connecté"], authorized: ["signal", "Autorisé"],
    configured: ["teal", "Configuré"], failed: ["red", "Erreur"], expired: ["orange", "Reconnexion requise"],
    disconnected: ["gray", "Déconnecté"], pending: ["gray", "En attente"],
  };
  const [color, label] = map[a.status] ?? ["gray", a.status];
  return <Badge color={color} variant={color === "signal" ? "light" : "outline"}>{label}</Badge>;
}

/** Guided form for an api_key / basic provider: named fields with inline help, no JSON. */
function ConfigureModal({ provider, onClose, onDone }: { provider: Provider; onClose: () => void; onDone: () => void }) {
  const { tenantId } = useTenant();
  const [values, setValues] = useState<Record<string, string>>(() => provider.account?.settings ?? {});
  const save = useMutation({
    mutationFn: async () => {
      const r = await api<{ account_id: string }>("/connectors/connect", { method: "POST", tenantId, body: { provider_code: provider.code, method: "api_key" } });
      const secrets: Record<string, string> = {}, settings: Record<string, string> = {};
      for (const f of provider.fields) { const v = values[f.name]; if (v) secrets[f.name] = v; }
      for (const f of provider.settings_fields) { const v = values[f.name]; if (v) settings[f.name] = v; }
      await api(`/connector-accounts/${r.account_id}/credentials`, { method: "POST", tenantId, body: { credential_type: "api_key", secrets, settings } });
      return api<{ status: string; error: string | null }>(`/connector-accounts/${r.account_id}/test`, { method: "POST", tenantId });
    },
    onSuccess: (res) => {
      if (res.status === "tested") notifications.show({ color: "teal", message: `${provider.name} connecté et testé.` });
      else notifications.show({ color: "orange", title: "Enregistré, mais le test a échoué", message: res.error ?? "" });
      onDone(); onClose();
    },
  });
  const missing = provider.fields.concat(provider.settings_fields).some((f) => f.required && !values[f.name]);
  return (
    <Modal opened onClose={onClose} title={<Text fw={600}>Configurer {provider.name}</Text>}>
      <Stack gap="sm">
        {provider.help_url && <Text size="xs" c="dimmed">Où trouver ces informations : <Anchor href={provider.help_url} target="_blank" rel="noreferrer">documentation du fournisseur <IconExternalLink size={11} /></Anchor></Text>}
        {provider.settings_fields.map((f) => (
          <TextInput key={f.name} label={f.label} required={f.required} type={f.type === "number" ? "number" : f.type === "url" ? "url" : "text"}
            placeholder={f.placeholder} description={f.help || undefined} value={values[f.name] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.currentTarget.value }))} />
        ))}
        {provider.fields.map((f) => (
          f.secret
            ? <PasswordInput key={f.name} label={f.label} required={f.required} placeholder={f.placeholder} description={f.help || undefined}
                value={values[f.name] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.currentTarget.value }))} />
            : <TextInput key={f.name} label={f.label} required={f.required} placeholder={f.placeholder} description={f.help || undefined}
                value={values[f.name] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.currentTarget.value }))} />
        ))}
        {save.error && <Alert color="red" py={6}>{err(save.error)}</Alert>}
        <Text size="xs" c="dimmed">Les secrets sont chiffrés côté serveur et ne sont jamais réaffichés.</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Annuler</Button>
          <Button loading={save.isPending} disabled={missing} onClick={() => save.mutate()}>Enregistrer et tester</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function ProviderCard({ provider, onChanged }: { provider: Provider; onChanged: () => void }) {
  const { tenantId, can } = useTenant();
  const manage = can("connectors.manage");
  const [configure, setConfigure] = useState(false);
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: Record<string, unknown> }) => api<{ authorization_url?: string; status?: string; error?: string | null }>(path, { method: "POST", tenantId, body: body ?? {} }),
  });
  const a = provider.account;
  const connected = a && ["tested", "connected", "authorized", "configured"].includes(a.status);
  const connect = (method?: "oauth" | "api_key") => {
    if (method === "api_key" || (provider.method === "api_key")) { setConfigure(true); return; }
    act.mutate({ path: "/connectors/connect", body: { provider_code: provider.code, method, return_to: `/t/${tenantId}/connectors` } }, {
      onSuccess: (r) => { if (r.authorization_url) window.location.assign(r.authorization_url); },
    });
  };
  const test = () => act.mutate({ path: `/connector-accounts/${a?.id}/test` }, { onSuccess: (r) => { notifications.show({ color: r.status === "tested" ? "teal" : "orange", message: r.status === "tested" ? "Test réussi." : (r.error ?? "Test échoué") }); onChanged(); } });
  const disconnect = () => act.mutate({ path: `/connector-accounts/${a?.id}/disconnect` }, { onSuccess: () => { notifications.show({ message: `${provider.name} déconnecté.` }); onChanged(); } });
  const disabled = provider.authorization_status === "disabled" || provider.authorization_status === "suspended";
  return (
    <Card padding="md" style={connected ? { borderColor: "var(--mantine-color-signal-7)" } : undefined}>
      <Group justify="space-between" mb={6} wrap="nowrap">
        <Text fw={600} size="sm" lineClamp={1}>{provider.name}</Text>
        {a ? <AccountState a={a} /> : disabled ? <Badge color="gray" variant="outline">Désactivé</Badge> : <Badge color="gray" variant="outline">Non connecté</Badge>}
      </Group>
      {a?.credential_hint && <Text size="xs" c="dimmed">Secret : {a.credential_hint}</Text>}
      {a?.status === "failed" && a.last_error && <Text size="xs" c="red" lineClamp={2}>{a.last_error}</Text>}
      {provider.method === "unsupported" && <Text size="xs" c="dimmed">Bientôt disponible.</Text>}
      {disabled && <Text size="xs" c="dimmed">Désactivé par le PILOTE pour votre espace.</Text>}
      {!disabled && manage && provider.method !== "unsupported" && (
        <Group gap={6} mt="sm">
          {connected ? (
            <>
              <Button size="compact-sm" variant="light" leftSection={<IconRefresh size={14} />} loading={act.isPending} onClick={test}>Tester</Button>
              {provider.method !== "api_key" && provider.oauth_available && <Button size="compact-sm" variant="subtle" onClick={() => connect("oauth")}>Reconnecter</Button>}
              <Button size="compact-sm" variant="subtle" color="red" onClick={disconnect}>Déconnecter</Button>
            </>
          ) : provider.method === "oauth" ? (
            <Button size="compact-sm" leftSection={<IconPlugConnected size={14} />} loading={act.isPending} disabled={!provider.oauth_available}
              onClick={() => connect("oauth")}>Se connecter avec {provider.family_label}</Button>
          ) : provider.method === "oauth_or_key" ? (
            <>
              <Button size="compact-sm" leftSection={<IconPlugConnected size={14} />} loading={act.isPending} disabled={!provider.oauth_available} onClick={() => connect("oauth")}>Se connecter avec {provider.family_label}</Button>
              <Button size="compact-sm" variant="light" leftSection={<IconKey size={14} />} onClick={() => connect("api_key")}>Jeton</Button>
            </>
          ) : (
            <Button size="compact-sm" leftSection={<IconKey size={14} />} onClick={() => connect("api_key")}>Configurer</Button>
          )}
        </Group>
      )}
      {configure && <ConfigureModal provider={provider} onClose={() => setConfigure(false)} onDone={onChanged} />}
      {provider.method === "oauth" && !provider.oauth_available && !disabled && <Text size="xs" c="dimmed" mt={6}>Connexion en un clic à activer par le PILOTE.</Text>}
    </Card>
  );
}

export function ConnectorsPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["connectors-catalog", tenantId], queryFn: () => api<Catalog>("/connectors/catalog", { tenantId }) });
  const refetch = () => void qc.invalidateQueries({ queryKey: ["connectors-catalog", tenantId] });
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    if (p.get("oauth") === "success") { notifications.show({ color: "teal", icon: <IconCheck size={16} />, message: "Compte connecté." }); refetch(); }
    else if (p.get("oauth") === "error") notifications.show({ color: "red", icon: <IconX size={16} />, message: "La connexion a été refusée." });
    if (p.get("oauth")) window.history.replaceState({}, "", window.location.pathname);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (q.isLoading) return <RobotLoader label="Chargement des connecteurs…" />;
  const providers = q.data?.providers ?? [];
  const cats = [...new Set(providers.map((p) => p.category))].sort((x, y) => (CATEGORIES[x] ?? x).localeCompare(CATEGORIES[y] ?? y));
  return (
    <Stack gap="lg">
      <PageHeader title="Connecteurs" subtitle="Connectez vos comptes en un clic quand c'est proposé, sinon via un formulaire guidé. Rien n'est simulé : chaque connexion est testée réellement." />
      {providers.some((p) => p.method !== "oauth" || p.oauth_available) ? null : (
        <Alert icon={<IconAlertTriangle size={16} />} color="gray">La connexion en un clic (Google, GitHub, Microsoft…) sera disponible une fois les applications OAuth enregistrées par le PILOTE.</Alert>
      )}
      {cats.map((cat) => (
        <div key={cat}>
          <Title order={5} mb="sm">{CATEGORIES[cat] ?? cat}</Title>
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3, xl: 4 }}>
            {providers.filter((p) => p.category === cat).map((p) => <ProviderCard key={p.code} provider={p} onChanged={refetch} />)}
          </SimpleGrid>
        </div>
      ))}
    </Stack>
  );
}

// ───────────────────────────── PILOTE: OAuth apps per family ─────────────────────────────
interface Family { family: string; label: string; console: string; steps: string[]; configured: boolean; redirect_uri: string; providers: string[] }

export function PilotOAuthClientsCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["pilot-oauth"], queryFn: () => api<Family[]>("/pilot/oauth-clients") });
  const [open, setOpen] = useState<Family | null>(null);
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const save = useMutation({
    mutationFn: () => api("/pilot/oauth-clients", { method: "POST", body: { family: open?.family, client_id: clientId, client_secret: secret } }),
    onSuccess: () => { notifications.show({ color: "teal", message: `OAuth ${open?.label} enregistré.` }); setOpen(null); setClientId(""); setSecret(""); void qc.invalidateQueries({ queryKey: ["pilot-oauth"] }); },
  });
  return (
    <Card withBorder padding="lg">
      <Title order={5} mb={4}>Connexions OAuth des connecteurs</Title>
      <Text size="sm" c="dimmed" mb="md">Enregistrez l'application OAuth une seule fois par fournisseur. Les tenants pourront ensuite connecter leur compte en un clic (« Se connecter avec… ») sans coller de clé.</Text>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {(q.data ?? []).map((f) => (
          <Card key={f.family} padding="sm">
            <Group justify="space-between" mb={4}>
              <Group gap={6}><ThemeIcon size="sm" variant="light" color={f.configured ? "signal" : "gray"}>{f.configured ? <IconCheck size={14} /> : <IconPlugConnected size={14} />}</ThemeIcon><Text fw={600} size="sm">{f.label}</Text></Group>
              <Badge size="xs" color={f.configured ? "signal" : "gray"} variant={f.configured ? "light" : "outline"}>{f.configured ? "Configuré" : "À configurer"}</Badge>
            </Group>
            <Text size="xs" c="dimmed" lineClamp={1}>{f.providers.join(", ")}</Text>
            <Button size="compact-xs" variant="light" mt="xs" onClick={() => setOpen(f)}>{f.configured ? "Modifier" : "Configurer"}</Button>
          </Card>
        ))}
      </SimpleGrid>
      <Modal opened={!!open} onClose={() => setOpen(null)} size="lg" title={<Text fw={600}>OAuth {open?.label}</Text>}>
        {open && (
          <Stack gap="sm">
            <List type="ordered" size="sm" spacing={4}>{open.steps.map((s) => <List.Item key={s}>{s}</List.Item>)}</List>
            <Anchor href={open.console} target="_blank" rel="noreferrer" size="sm">Ouvrir la console {open.label} <IconExternalLink size={12} /></Anchor>
            <TextInput label="URI de redirection (à coller chez le fournisseur)" readOnly value={open.redirect_uri}
              onFocus={(e) => e.currentTarget.select()} description="Copiez cette valeur exacte dans l'application OAuth." />
            <TextInput label="Client ID" value={clientId} onChange={(e) => setClientId(e.currentTarget.value)} />
            <PasswordInput label="Client secret" value={secret} onChange={(e) => setSecret(e.currentTarget.value)} description="Chiffré côté serveur, jamais réaffiché." />
            {save.error && <Alert color="red" py={6}>{err(save.error)}</Alert>}
            <Group justify="flex-end"><Button variant="default" onClick={() => setOpen(null)}>Annuler</Button>
              <Button loading={save.isPending} disabled={!clientId || !secret} onClick={() => save.mutate()}>Enregistrer</Button></Group>
          </Stack>
        )}
      </Modal>
    </Card>
  );
}
