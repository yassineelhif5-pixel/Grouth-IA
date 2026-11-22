import { Alert, Anchor, Badge, Button, Card, Group, MultiSelect, Paper, ScrollArea, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { useTenant } from "@/hooks/useMe";
import { api, ApiError } from "@/services/api";
import { formatDate } from "@/utils/format";

type Row = Record<string, unknown>;
interface Account { id: string; provider: string; display_name: string | null; status: string; site_url: string | null }
interface Setup { accounts: Account[]; themes: { themes: { theme: string; why: string }[]; method?: string }; categories?: { id: number; name: string }[];
  categories_error?: string }
interface Msg { role: "user" | "assistant"; content: string }
interface ChatRes { reply: string; plan: Row; ready: boolean; summary: string | null; source: string }
interface History { plans: Row[]; articles: Row[]; events: Row[] }

const errText = (e: unknown) => (e instanceof ApiError ? e.message : String((e as Error)?.message ?? e));
const CMS_LABEL: Record<string, string> = { wordpress: "WordPress", ghost: "Ghost", rest_cms: "CMS (API REST)" };

/** Blog autopilot: CMS connector → theme → conversation with the publication assistant → confirmation → history. */
export function AutopilotPage() {
  const { tenantId, can } = useTenant();
  const qc = useQueryClient();
  const write = can("content.publish");
  const products = useQuery({ queryKey: ["/products", tenantId, "autopilot"], queryFn: () => api<{ results: Row[] }>("/products", { tenantId }) });
  const [product, setProduct] = useState<string | null>(null);
  const [account, setAccount] = useState<string | null>(null);
  const [theme, setTheme] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const setup = useQuery({ queryKey: ["autopilot-setup", tenantId, product, account], queryFn: () => api<Setup>("/content/autopilot/setup",
    { tenantId, query: { product_id: product ?? undefined, account_id: account ?? undefined } }) });
  const accounts = setup.data?.accounts ?? [];
  const acc = accounts.find((a) => a.id === account);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [plan, setPlan] = useState<Row>({});
  const [ready, setReady] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const history = useQuery({ queryKey: ["autopilot-history", tenantId], queryFn: () => api<History>("/content/autopilot/history", { tenantId }) });

  const chat = useMutation({
    mutationFn: (message: string) => api<ChatRes>("/content/autopilot/chat", { method: "POST", tenantId, body: {
      message, history: messages, plan: { ...plan, account_id: account, product_id: product, theme, site: acc?.site_url,
        category_ids: categories.map(Number) } } }),
    onSuccess: (r, message) => { setPlan(r.plan); setReady(r.ready ? r.summary : null);
      setMessages((m) => [...m, ...(message ? [{ role: "user" as const, content: message }] : []), { role: "assistant", content: r.reply }]); },
  });
  const confirm = useMutation({
    mutationFn: () => api<{ confirmation: string; summary: string }>("/content/autopilot/confirm", { method: "POST", tenantId, body: { plan } }),
    onSuccess: (r) => { setConfirmed(`${r.confirmation} ${r.summary}`); setReady(null); setMessages([]); setPlan({});
      void qc.invalidateQueries({ queryKey: ["autopilot-history"] }); },
  });
  const act = useMutation({
    mutationFn: ({ id, op }: { id: string; op: string }) => api<Row>(`/content/autopilot/${id}/${op}`, { method: "POST", body: {}, tenantId }),
    onSuccess: (_r, v) => { notifications.show({ color: "green", message: v.op === "publish" ? "Article publié" : v.op === "run" ? "Article en cours de rédaction" : "Programme mis à jour" });
      void qc.invalidateQueries({ queryKey: ["autopilot-history"] }); },
  });
  const send = () => { if (input.trim()) { chat.mutate(input.trim()); setInput(""); } };
  const canChat = Boolean(product && account && theme.trim());

  return (
    <Stack>
      <PageHeader title="Publication automatique d'articles" subtitle="Des articles rédigés par l'IA et publiés sur votre site pour remonter dans Google et les assistants IA" />
      {confirmed && <Alert color="green" withCloseButton onClose={() => setConfirmed(null)} title="Programme confirmé">{confirmed}</Alert>}

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card withBorder>
          <Title order={4} mb="sm">1. Site de publication</Title>
          <Select label="Produit à promouvoir" value={product} onChange={setProduct} mb="sm"
            data={(products.data?.results ?? []).map((p) => ({ value: String(p.id), label: String(p.name) }))} />
          {accounts.length === 0 ? <Alert color="yellow" title="Aucun site connecté">
            Connectez votre site dans <Anchor component={Link} to={`/t/${tenantId}/connectors`}>Connecteurs</Anchor> : WordPress (adresse du site,
            identifiant et mot de passe d'application créé dans Utilisateurs → Profil), Ghost (clé Admin API) ou tout CMS avec API REST.
            Cliquez ensuite sur « Tester » pour vérifier la connexion.
          </Alert> : <Select label="Publier sur" value={account} onChange={(v) => { setAccount(v); setCategories([]); }}
            data={accounts.map((a) => ({ value: a.id, label: `${CMS_LABEL[a.provider] ?? a.provider} — ${a.site_url ?? a.display_name ?? ""}` }))} />}
          {acc?.provider === "wordpress" && <MultiSelect mt="sm" label="Catégories WordPress (facultatif)" value={categories} onChange={setCategories}
            data={(setup.data?.categories ?? []).map((c) => ({ value: String(c.id), label: c.name }))}
            description={setup.data?.categories_error ? `Catégories indisponibles : ${setup.data.categories_error}` : undefined} />}
        </Card>

        <Card withBorder>
          <Title order={4} mb="sm">2. Thème des articles</Title>
          <TextInput label="Thème" placeholder="Choisissez une suggestion ou écrivez votre thème" value={theme} onChange={(e) => setTheme(e.currentTarget.value)} />
          <Group gap={6} mt="sm">
            {(setup.data?.themes.themes ?? []).map((t) => <Badge key={t.theme} variant={t.theme === theme ? "filled" : "light"} style={{ cursor: "pointer" }}
              title={t.why} onClick={() => setTheme(t.theme)}>{t.theme}</Badge>)}
          </Group>
          {!product && <Text size="xs" c="dimmed" mt="xs">Choisissez un produit pour voir les thèmes suggérés.</Text>}
        </Card>
      </SimpleGrid>

      <Card withBorder>
        <Group justify="space-between" mb="sm"><Title order={4}>3. Programmer avec l'assistant</Title>
          {messages.length === 0 && <Button disabled={!canChat || !write} onClick={() => chat.mutate("")}>Démarrer la discussion</Button>}</Group>
        {!canChat && <Text size="sm" c="dimmed">Choisissez le produit, le site et le thème pour démarrer.</Text>}
        {messages.length > 0 && <>
          <ScrollArea h={280} mb="sm"><Stack gap="xs">
            {messages.map((m, i) => <Paper key={i} p="sm" radius="md" withBorder maw="85%" ml={m.role === "user" ? "auto" : 0}
              bg={m.role === "user" ? "var(--mantine-color-indigo-light)" : undefined}><Text size="sm">{m.content}</Text></Paper>)}
          </Stack></ScrollArea>
          {ready ? <Alert color="blue" title="Récapitulatif">
            <Text size="sm" mb="sm">{ready}</Text>
            <Group><Button onClick={() => confirm.mutate()} loading={confirm.isPending}>Confirmer le programme</Button>
              <Button variant="default" onClick={() => setReady(null)}>Modifier</Button></Group>
          </Alert> : <Group align="flex-end">
            <TextInput style={{ flex: 1 }} placeholder="Votre réponse…" value={input} onChange={(e) => setInput(e.currentTarget.value)}
              onKeyDown={(e) => { if (e.key === "Enter") send(); }} />
            <Button onClick={send} loading={chat.isPending} disabled={!input.trim()}>Envoyer</Button></Group>}
          {(chat.isError || confirm.isError) && <Alert color="red" mt="sm">{errText(chat.error ?? confirm.error)}</Alert>}
        </>}
      </Card>

      <Card withBorder>
        <Title order={4} mb="sm">Historique</Title>
        <Text fw={600} size="sm" mb={4}>Programmes confirmés</Text>
        <Table mb="md"><Table.Tbody>
          {(history.data?.plans ?? []).map((p) => <Table.Tr key={String(p.id)}>
            <Table.Td><Text size="sm" fw={500}>{String(p.name)}</Text><Text size="xs" c="dimmed">{String(p.description ?? "")}</Text></Table.Td>
            <Table.Td><StatusBadge value={p.status as string} /></Table.Td>
            <Table.Td><Text size="xs">Prochain : {formatDate(p.next_run_at as string)}</Text><Text size="xs" c="dimmed">Confirmé le {formatDate(p.created_at as string)}</Text></Table.Td>
            <Table.Td><Group gap={4} justify="flex-end">
              <Button size="xs" variant="light" disabled={!write || p.status !== "active"} onClick={() => act.mutate({ id: String(p.id), op: "run" })}>Rédiger maintenant</Button>
              <Button size="xs" variant="subtle" disabled={!write} onClick={() => act.mutate({ id: String(p.id), op: p.status === "active" ? "pause" : "resume" })}>
                {p.status === "active" ? "Pause" : "Reprendre"}</Button></Group></Table.Td>
          </Table.Tr>)}
        </Table.Tbody></Table>
        {history.data?.plans.length === 0 && <Text size="sm" c="dimmed" mb="md">Aucun programme pour l'instant.</Text>}
        <Text fw={600} size="sm" mb={4}>Articles</Text>
        <Table><Table.Tbody>
          {(history.data?.articles ?? []).map((a) => <Table.Tr key={String(a.id)}>
            <Table.Td><Text size="sm">{String(a.title)}</Text><Text size="xs" c="dimmed">Rédigé le {formatDate(a.created_at as string)}
              {a.seo_score != null ? ` · SEO ${Math.round(Number(a.seo_score))} · GEO ${Math.round(Number(a.geo_score))}` : ""}</Text></Table.Td>
            <Table.Td>{a.publication_status ? <StatusBadge value={a.publication_status as string} /> : <Badge color="orange" variant="light">À valider</Badge>}
              {a.error_message ? <Text size="xs" c="red">{String(a.error_message)}</Text> : null}</Table.Td>
            <Table.Td>{a.external_url ? <Anchor size="sm" href={String(a.external_url)} target="_blank" rel="noopener noreferrer">Voir l'article</Anchor>
              : !a.publication_status && <Button size="xs" disabled={!write} onClick={() => act.mutate({ id: String(a.id), op: "publish" })}>Valider et publier</Button>}
              {a.published_at ? <Text size="xs" c="dimmed">Publié le {formatDate(a.published_at as string)}</Text> : null}</Table.Td>
          </Table.Tr>)}
        </Table.Tbody></Table>
        {history.data?.articles.length === 0 && <Text size="sm" c="dimmed">Aucun article pour l'instant.</Text>}
        {act.isError && <Alert color="red" mt="sm">{errText(act.error)}</Alert>}
      </Card>
    </Stack>
  );
}
