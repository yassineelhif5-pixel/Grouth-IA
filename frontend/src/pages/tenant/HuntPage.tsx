import { Alert, Anchor, Badge, Button, Card, Drawer, Group, Modal, Progress, SegmentedControl, Select, SimpleGrid, Stack, Text, Textarea,
  TextInput, Timeline, Title, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { useTenant } from "@/hooks/useMe";
import { api, ApiError } from "@/services/api";
import { formatDate } from "@/utils/format";

type Row = Record<string, unknown>;
interface Kw { keyword: string; weight?: number; intent?: string; why?: string }
interface Company { siren: string; name: string; category: string | null; category_label: string; naf_label: string | null; employees: number | null;
  city: string | null; officers: { name: string; role: string | null }[] }
interface Contact { id: string; first_name: string | null; last_name: string | null; email: string | null; job_title: string | null; consent_status: string }
interface CardRow { id: string; status: string; score: string | null; need_detected: string | null; company: string | null; domain: string | null;
  industry: string | null; company_data: Row | null; contacts: Contact[] | null; last_sent_at: string | null; sent_count: number;
  last_reply_at: string | null; trial_clicked: boolean }
interface Draft { to: string | null; subject: string; body: string; contacts: Contact[]; method: string }

const errText = (e: unknown) => (e instanceof ApiError ? e.message : String((e as Error)?.message ?? e));
const scoreColor = (s: number) => (s >= 70 ? "green" : s >= 45 ? "yellow" : "gray");

/** Prospect hunting: site keywords → open-data companies → contacts → AI-ranked cards → reviewed e-mail → full follow-up. */
export function HuntPage() {
  const { tenantId, can } = useTenant();
  const qc = useQueryClient();
  const write = can("prospects.write");
  const products = useQuery({ queryKey: ["/products", tenantId, "hunt"], queryFn: () => api<{ results: Row[] }>("/products", { tenantId }) });
  const [product, setProduct] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  const scan = useMutation({ mutationFn: () => api<{ keywords: Kw[]; suggestions: Kw[]; suggestions_method: string; pages_scanned: string[] }>(
    "/prospects/hunt/keywords", { method: "POST", body: { url }, tenantId }) });
  const search = useMutation({ mutationFn: () => api<{ results: Company[]; total: number }>("/prospects/hunt/companies",
    { tenantId, query: { q: query, category: category === "all" ? undefined : category } }) });
  const add = useMutation({
    mutationFn: (companies: Company[]) => api<{ created: number; already_known: number }>("/prospects/hunt/companies/add",
      { method: "POST", body: { companies, product_id: product }, tenantId }),
    onSuccess: (r) => { setSelected({}); notifications.show({ color: "green", message: `${r.created} prospect(s) ajouté(s), ${r.already_known} déjà connu(s)` });
      void qc.invalidateQueries({ queryKey: ["hunt-board"] }); },
  });
  const board = useQuery({ queryKey: ["hunt-board", tenantId, product], queryFn: () => api<CardRow[]>("/prospects/hunt/board", { tenantId, query: { product: product ?? undefined } }) });
  const picked = (search.data?.results ?? []).filter((c) => selected[c.siren]);

  return (
    <Stack>
      <PageHeader title="Chasse aux prospects" subtitle="Mots-clés du site, entreprises ciblées, contacts, e-mail relu avant envoi et suivi complet" />
      <Select label="Produit à promouvoir" placeholder="Choisir un produit" w={360} value={product} onChange={(v) => {
        setProduct(v); const p = products.data?.results.find((x) => x.id === v); if (p?.url) setUrl(String(p.url)); }}
        data={(products.data?.results ?? []).map((p) => ({ value: String(p.id), label: String(p.name) }))} />

      <Card withBorder>
        <Title order={4} mb="xs">1. Mots-clés du site</Title>
        <Group align="flex-end">
          <TextInput label="Site à analyser" placeholder="https://votre-site.fr" value={url} onChange={(e) => setUrl(e.currentTarget.value)} style={{ flex: 1 }} />
          <Button onClick={() => scan.mutate()} loading={scan.isPending} disabled={!url || !write}>Analyser</Button>
        </Group>
        {scan.isError && <Alert color="red" mt="sm">{errText(scan.error)}</Alert>}
        {scan.data && <SimpleGrid cols={{ base: 1, md: 2 }} mt="md">
          <div>
            <Text fw={600} mb={6}>Présents sur le site ({scan.data.pages_scanned.length} pages)</Text>
            <Group gap={6}>{scan.data.keywords.map((k) => <Badge key={k.keyword} variant="light" style={{ cursor: "pointer" }}
              onClick={() => setQuery(k.keyword)}>{k.keyword} · {k.weight}</Badge>)}</Group>
          </div>
          <div>
            <Text fw={600} mb={6}>Nouveaux mots-clés à fort potentiel {scan.data.suggestions_method === "ai" ? "(IA)" : "(règles, IA non configurée)"}</Text>
            <Group gap={6}>{scan.data.suggestions.map((k) => <Tooltip key={k.keyword} label={k.why} multiline w={260}>
              <Badge color="grape" variant="light" style={{ cursor: "pointer" }} onClick={() => setQuery(k.keyword)}>{k.keyword}</Badge></Tooltip>)}</Group>
          </div>
        </SimpleGrid>}
      </Card>

      <Card withBorder>
        <Title order={4} mb="xs">2. Entreprises ciblées</Title>
        <Text size="xs" c="dimmed" mb="sm">Source : registre public des entreprises françaises (open data). Cliquez sur un mot-clé ci-dessus pour le reprendre.</Text>
        <Group align="flex-end">
          <TextInput label="Secteur, activité ou mot-clé" value={query} onChange={(e) => setQuery(e.currentTarget.value)} style={{ flex: 1 }} />
          <SegmentedControl value={category} onChange={setCategory} data={[{ value: "all", label: "Toutes" }, { value: "GE", label: "Grands groupes" },
            { value: "ETI", label: "ETI" }, { value: "PME", label: "PME" }]} />
          <Button onClick={() => search.mutate()} loading={search.isPending} disabled={!query}>Chercher</Button>
        </Group>
        {search.isError && <Alert color="red" mt="sm">{errText(search.error)}</Alert>}
        {search.data && <>
          <Group justify="space-between" mt="md" mb="xs"><Text size="sm">{search.data.total} entreprise(s) trouvée(s)</Text>
            <Button size="xs" disabled={!picked.length || !write} loading={add.isPending} onClick={() => add.mutate(picked)}>
              Ajouter {picked.length || ""} aux prospects</Button></Group>
          <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
            {search.data.results.map((co) => (
              <Card key={co.siren} withBorder padding="sm" style={selected[co.siren] ? { borderColor: "var(--mantine-color-indigo-6)" } : undefined}
                onClick={() => setSelected({ ...selected, [co.siren]: !selected[co.siren] })}>
                <Group justify="space-between"><Text fw={600} lineClamp={1}>{co.name}</Text><Badge size="sm">{co.category_label}</Badge></Group>
                <Text size="xs" c="dimmed" lineClamp={1}>{co.naf_label ?? "Activité non renseignée"} · {co.city ?? ""}</Text>
                {co.officers.length > 0 && <Text size="xs" mt={4}>{co.officers.slice(0, 2).map((o) => `${o.name} (${o.role ?? "dirigeant"})`).join(", ")}</Text>}
              </Card>))}
          </SimpleGrid>
        </>}
      </Card>

      <Title order={4}>3. Prospects classés par intérêt</Title>
      {board.data?.length === 0 && <Text c="dimmed">Aucun prospect pour l'instant : ajoutez des entreprises à l'étape 2.</Text>}
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {board.data?.map((p) => <ProspectCard key={p.id} p={p} tenantId={tenantId} write={write} />)}
      </SimpleGrid>
    </Stack>
  );
}

function ProspectCard({ p, tenantId, write }: { p: CardRow; tenantId: string; write: boolean }) {
  const qc = useQueryClient();
  const [domain, setDomain] = useState(p.domain ?? "");
  const [mailOpen, setMailOpen] = useState(false);
  const [histOpen, setHistOpen] = useState(false);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["hunt-board"] });
  const act = useMutation({
    mutationFn: (op: string) => api<Row>(`/prospects/hunt/${p.id}/${op}`, { method: "POST", body: op === "site-contacts" ? { domain } : {}, tenantId }),
    onSuccess: (r, op) => { refresh(); if (op === "site-contacts") notifications.show({ message: `${(r.emails as string[]).length} adresse(s) générique(s) trouvée(s)` }); },
  });
  const score = p.score ? Math.round(Number(p.score)) : 0;
  const cat = (p.company_data?.category_label as string) ?? "";
  const contacts = p.contacts ?? [];
  return (
    <Card withBorder padding="md">
      <Group justify="space-between" align="flex-start">
        <div style={{ minWidth: 0 }}>
          <Text fw={700} lineClamp={1}>{p.company ?? "Prospect"}</Text>
          <Text size="xs" c="dimmed" lineClamp={1}>{[cat, p.industry, p.company_data?.city as string].filter(Boolean).join(" · ")}</Text>
        </div>
        <Tooltip label={p.need_detected ?? ""} multiline w={300}><Badge size="lg" color={scoreColor(score)}>{score}/100</Badge></Tooltip>
      </Group>
      <Progress value={score} color={scoreColor(score)} size="xs" my="xs" />
      <Text size="xs" lineClamp={2} mb="xs">{p.need_detected}</Text>
      <Stack gap={2} mb="xs">{contacts.slice(0, 4).map((c) => (
        <Text key={c.id} size="xs">{[c.first_name, c.last_name].filter(Boolean).join(" ") || "—"} · {c.job_title ?? ""}{c.email ? ` · ${c.email}` : ""}
          {c.consent_status === "opted_out" && <Badge size="xs" color="red" ml={4}>désinscrit</Badge>}</Text>))}</Stack>
      <Group gap={6} mb="xs">
        <StatusBadge value={p.status} />
        {p.sent_count > 0 && <Badge size="sm" variant="light">{p.sent_count} e-mail(s) · {formatDate(p.last_sent_at as string)}</Badge>}
        {p.last_reply_at && <Badge size="sm" color="green" variant="light">A répondu</Badge>}
        {p.trial_clicked && <Badge size="sm" color="grape" variant="light">Lien d'essai cliqué</Badge>}
      </Group>
      {!contacts.some((c) => c.email) && <Group gap={6} align="flex-end" mb="xs">
        <TextInput size="xs" placeholder="site de l'entreprise (ex. acme.fr)" value={domain} onChange={(e) => setDomain(e.currentTarget.value)} style={{ flex: 1 }} />
        <Button size="xs" variant="light" disabled={!domain || !write} loading={act.isPending && act.variables === "site-contacts"} onClick={() => act.mutate("site-contacts")}>Contacts du site</Button>
      </Group>}
      {act.isError && <Alert color="orange" mb="xs" p="xs">{errText(act.error)}</Alert>}
      <Group gap={6}>
        <Button size="xs" disabled={!contacts.some((c) => c.email && c.consent_status !== "opted_out") || !write} onClick={() => setMailOpen(true)}>
          {p.sent_count > 0 ? "Relancer" : "Préparer l'e-mail"}</Button>
        <Button size="xs" variant="default" onClick={() => setHistOpen(true)}>Historique</Button>
        <Button size="xs" variant="subtle" disabled={!write} onClick={() => act.mutate("enrich")}>Contacts nominatifs</Button>
        <Button size="xs" variant="subtle" disabled={!write} onClick={() => act.mutate("score")}>Re-noter</Button>
      </Group>
      {mailOpen && <MailModal prospectId={p.id} tenantId={tenantId} onClose={() => { setMailOpen(false); refresh(); }} />}
      <Drawer opened={histOpen} onClose={() => setHistOpen(false)} position="right" size="lg" title={`Historique — ${p.company ?? ""}`}>
        {histOpen && <History prospectId={p.id} tenantId={tenantId} />}
      </Drawer>
    </Card>
  );
}

function MailModal({ prospectId, tenantId, onClose }: { prospectId: string; tenantId: string; onClose: () => void }) {
  const mailboxes = useQuery({ queryKey: ["/email/mailboxes", tenantId, "hunt"], queryFn: () => api<{ results: Row[] } | Row[]>("/email/mailboxes", { tenantId }) });
  const boxes = (Array.isArray(mailboxes.data) ? mailboxes.data : mailboxes.data?.results ?? []).filter((m) => m.send_enabled !== false);
  const [contactId, setContactId] = useState<string | null>(null);
  const draft = useQuery({ queryKey: ["hunt-draft", prospectId, contactId], queryFn: () => api<Draft>(`/prospects/hunt/${prospectId}/draft`,
    { method: "POST", body: { contact_id: contactId }, tenantId }) });
  const [edit, setEdit] = useState<{ subject: string; body: string } | null>(null);
  const [mailbox, setMailbox] = useState<string | null>(null);
  const subject = edit?.subject ?? draft.data?.subject ?? "";
  const body = edit?.body ?? draft.data?.body ?? "";
  const send = useMutation({
    mutationFn: () => api<{ follow_up: boolean }>(`/prospects/hunt/${prospectId}/send`, { method: "POST", tenantId,
      body: { mailbox_id: mailbox ?? boxes[0]?.id, to: draft.data?.to, subject, body } }),
    onSuccess: (r) => { notifications.show({ color: "green", message: r.follow_up ? "Relance envoyée dans la même conversation" : "E-mail envoyé" }); onClose(); },
  });
  return (
    <Modal opened onClose={onClose} size="xl" title="E-mail de prospection — relisez avant d'envoyer">
      {draft.isLoading && <Text>Préparation…</Text>}
      {draft.isError && <Alert color="red">{errText(draft.error)}</Alert>}
      {draft.data && <Stack>
        <Group grow>
          <Select label="Destinataire" value={contactId ?? draft.data.contacts.find((c) => c.email === draft.data?.to)?.id ?? null}
            onChange={(v) => { setContactId(v); setEdit(null); }} allowDeselect={false}
            data={draft.data.contacts.map((c) => ({ value: c.id, label: `${c.email} ${c.job_title ? `(${c.job_title})` : ""}` }))} />
          <Select label="Envoyer depuis" placeholder={boxes.length ? "Boîte d'envoi" : "Aucune boîte configurée"} value={mailbox ?? (boxes[0]?.id as string) ?? null}
            onChange={setMailbox} data={boxes.map((m) => ({ value: String(m.id), label: String(m.address) }))} />
        </Group>
        <TextInput label="Objet" value={subject} onChange={(e) => setEdit({ subject: e.currentTarget.value, body })} />
        <Textarea label={`Message ${draft.data.method === "ai" ? "(rédigé par l'IA)" : "(modèle)"}`} autosize minRows={14} value={body}
          onChange={(e) => setEdit({ subject, body: e.currentTarget.value })} />
        <Text size="xs" c="dimmed">Le lien d'essai est suivi (clic = demande de contact dans l'historique). Le lien de désinscription doit rester dans le message.</Text>
        {!boxes.length && <Alert color="yellow">Configurez une boîte d'envoi dans Email Center pour pouvoir envoyer.</Alert>}
        {send.isError && <Alert color="red">{errText(send.error)}</Alert>}
        <Group justify="flex-end"><Button variant="default" onClick={onClose}>Annuler</Button>
          <Button onClick={() => send.mutate()} loading={send.isPending} disabled={!boxes.length || !draft.data.to}>Envoyer</Button></Group>
      </Stack>}
    </Modal>
  );
}

function History({ prospectId, tenantId }: { prospectId: string; tenantId: string }) {
  const h = useQuery({ queryKey: ["hunt-history", prospectId], queryFn: () => api<{ emails: Row[]; events: Row[];
    summary: { sent: number; last_sent_at: string | null; replied: boolean; last_reply_at: string | null; trial_clicks: number; contact_request: boolean } }>(
    `/prospects/hunt/${prospectId}/history`, { tenantId }) });
  if (!h.data) return <Text>Chargement…</Text>;
  const s = h.data.summary;
  const items = [
    ...h.data.emails.map((e) => ({ at: e.at as string, title: e.direction === "outbound" ? `E-mail envoyé — ${e.status as string}` : "Réponse reçue",
      text: `${e.subject as string}${e.classification ? ` · ${e.classification as string}` : ""}`, color: e.direction === "outbound" ? "indigo" : "green" })),
    ...h.data.events.filter((e) => e.activity_type !== "email").map((e) => ({ at: e.at as string, title: e.summary as string, text: "", color: "grape" })),
  ].sort((a, b) => (a.at < b.at ? 1 : -1));
  return (
    <Stack>
      <Group gap={6}>
        <Badge variant="light">{s.sent} envoi(s){s.last_sent_at ? ` · dernier ${formatDate(s.last_sent_at)}` : ""}</Badge>
        <Badge color={s.replied ? "green" : "gray"} variant="light">{s.replied ? `Réponse le ${formatDate(s.last_reply_at as string)}` : "Pas de réponse"}</Badge>
        <Badge color={s.contact_request ? "grape" : "gray"} variant="light">{s.contact_request ? "Demande de contact" : "Aucune demande"}</Badge>
      </Group>
      <Timeline bulletSize={14} lineWidth={2}>
        {items.map((it, i) => <Timeline.Item key={i} color={it.color} title={it.title}>
          {it.text && <Text size="sm">{it.text}</Text>}<Text size="xs" c="dimmed">{formatDate(it.at)}</Text></Timeline.Item>)}
      </Timeline>
      {!items.length && <Text c="dimmed">Aucun échange pour l'instant.</Text>}
      <Anchor size="xs" c="dimmed">Les réponses sont rattachées automatiquement à la conversation et classées par l'IA dans Email Center.</Anchor>
    </Stack>
  );
}
