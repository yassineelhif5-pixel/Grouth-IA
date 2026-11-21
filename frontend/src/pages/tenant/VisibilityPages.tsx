import {
  ActionIcon, Affix, Alert, Anchor, Badge, Box, Button, Card, Checkbox, Code, Divider, Drawer, Grid, Group, Loader, Modal, NumberInput, Paper,
  Progress, ScrollArea, SegmentedControl, Select, SimpleGrid, Stack, Stepper, Table, Tabs, Text, Textarea, TextInput, ThemeIcon, Title,
  Tooltip, UnstyledButton,
} from "@mantine/core";
import {
  IconAlertTriangle, IconBrain, IconCheck, IconCircleCheck, IconCircleDashed, IconDownload, IconInfoCircle, IconMessageChatbot,
  IconPlayerPlay, IconPlus, IconPrinter, IconRadar, IconRobot, IconSend, IconSparkles, IconTrash, IconX,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { useMe, useTenant } from "@/hooks/useMe";
import { api, ApiError } from "@/services/api";
import { formatDate } from "@/utils/format";

// ───────────────────────────── types ─────────────────────────────
interface Kpi { code: string; label: string; value: number | null; status: "observed" | "connected" | "not_connected" | "no_data"; source: string; trend: number | null; unit: string | null; note: string | null }
interface KpiResponse { kpis: Kpi[]; last_audit_at: string | null; connectors: Record<string, boolean> }
interface Check { code: string; label: string; status: "ok" | "warning" | "error" | "info"; detail: string; evidence: Record<string, unknown> }
interface SiteFinding { url: string; score: number; checks: Check[]; pages_crawled: number; sitemap_urls_count: number; seo_score: number }
interface Keyword { keyword: string; score: number; occurrences: number }
interface Competitor { name: string; url: string; source: string; score?: number; keywords?: Keyword[]; jsonld_types?: string[]; has_llms_txt?: boolean; error?: string }
interface Summary { source: "ai" | "rules"; model?: string; summary: string; what_to_do: string[]; what_to_publish: { title: string; format?: string; channel?: string; keyword?: string | null }[]; quick_wins: string[]; kpis: string[]; note?: string }
interface Audit {
  id: string; status: string; progress: number; step: string; score: number | null; error: string | null; audit_type: string; profile_name?: string;
  site_findings: { sites?: SiteFinding[]; keywords?: Keyword[]; domain?: string }; competitor_findings: { competitors?: Competitor[]; keyword_gap?: { keyword: string; competitors: string[] }[] };
  ai_summary: Summary | Record<string, never>; created_at: string; finished_at: string | null;
}
interface Recommendation { id: string; category: string; code: string; title: string; detail: string | null; priority: "critical" | "high" | "medium" | "low"; impact: string | null; effort: string | null; apply_mode: string; channel: string | null; status: string; frequency: string | null; times_per_period: number | null }
interface Asset { id: string; asset_type: string; filename: string; size: number }
interface RoadmapItem { id: string; phase: "now" | "next" | "later"; area: string; title: string; detail: string | null; priority: string; status: string; kpi: string | null }
interface Channel { code: string; name: string; why: string; connector: string[] }
interface Report { audit: Audit; recommendations: Recommendation[]; assets: Asset[]; roadmap: RoadmapItem[]; channels: Channel[]; kpis: KpiResponse }
interface Profile { id: string; name: string; site_urls: string[]; created_at: string }
interface Correction { kind: "file" | "content" | "manual"; filename?: string | null; content?: string; truncated?: boolean; cms_available?: boolean; content_type?: string; keyword?: string | null; channel?: string; objective?: string | null; plan?: string[]; how: string }
interface Preview { id: string; title: string; apply_mode: string; channel: string | null; priority: Recommendation["priority"]; frequency: string; times_per_period: number; recurring_allowed: boolean; correction: Correction }
interface PlanChoice { mode: "now" | "schedule"; frequency: string; times: number }
interface Candidate { name: string; url: string; source: "site_mentions" | "known" | "ai_suggested"; evidence?: string[]; mentions?: number }
interface DiscoverResult { site: string; name: string | null; candidates: Candidate[]; ai_available: boolean; note: string | null }
interface Execution { id: string; title: string; apply_mode: string; channel: string | null; frequency: string | null; times_per_period: number | null; scheduler_id: string | null; next_run_at: string | null; autonomy: string | null; run_id: string | null; state: "ready" | "planned" | "queued" | "running" | "succeeded" | "awaiting_approval" | "failed" | "cancelled"; progress: number; label: string; started_at: string | null; completed_at: string | null; content_id: string | null; can_run_now: boolean }

const PRIORITY: Record<Recommendation["priority"], { color: string; label: string }> = {
  critical: { color: "red", label: "Critique" }, high: { color: "orange", label: "Haute" }, medium: { color: "yellow", label: "Moyenne" }, low: { color: "gray", label: "Basse" },
};
const CHECK_ICON: Record<Check["status"], ReactNode> = {
  ok: <IconCircleCheck size={18} color="var(--mantine-color-signal-5)" />, warning: <IconAlertTriangle size={18} color="var(--mantine-color-yellow-5)" />,
  error: <IconX size={18} color="var(--mantine-color-red-5)" />, info: <IconInfoCircle size={18} color="var(--mantine-color-dimmed)" />,
};
const FREQUENCIES = [{ value: "once", label: "Une fois" }, { value: "daily", label: "Par jour" }, { value: "weekly", label: "Par semaine" }, { value: "monthly", label: "Par mois" }];
const MODE_LABEL: Record<string, string> = { generated_file: "Fichier prêt à déployer", ai_content: "Contenu rédigé par l'IA", auto_connector: "Publication via connecteur", manual: "Action manuelle" };

function errorText(e: unknown): string { return e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e); }

/** Observed data (teal) vs AI output (violet): the distinction the product promises, shown everywhere. */
export function NatureBadge({ nature }: { nature: "observed" | "ai" | "rules" | "not_connected" | "no_data" }) {
  const map = { observed: ["signal", "Observé"], ai: ["aurora", "Généré par IA"], rules: ["gray", "Règles"], not_connected: ["gray", "Non connecté"], no_data: ["gray", "Pas encore de données"] } as const;
  const [color, label] = map[nature];
  return <Badge color={color} variant={nature === "observed" || nature === "ai" ? "light" : "outline"} size="sm">{label}</Badge>;
}

// ───────────────────────────── KPI grid ─────────────────────────────
export function KpiGrid({ data }: { data: KpiResponse | undefined }) {
  const { tenantId } = useTenant();
  if (!data) return <Loader size="sm" />;
  return (
    <SimpleGrid cols={{ base: 1, xs: 2, md: 3, xl: 4 }} spacing="md">
      {data.kpis.map((k) => {
        const live = k.status === "observed" || k.status === "connected";
        return (
          <Card key={k.code} padding="md" style={live ? undefined : { borderStyle: "dashed", background: "transparent" }}>
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <Text size="sm" c="dimmed">{k.label}</Text>
              <NatureBadge nature={live ? "observed" : (k.status as "not_connected" | "no_data")} />
            </Group>
            {live && k.value !== null ? (
              <Group gap={6} align="baseline" mt={6}>
                <Text className="gi-num" fz={30} fw={600} ff="heading">{k.value}{k.unit === "%" ? "%" : ""}</Text>
                {k.unit && k.unit !== "%" && <Text c="dimmed" size="sm">{k.unit}</Text>}
                {k.trend !== null && k.trend !== 0 && <Badge color={k.trend > 0 ? "signal" : "red"} size="sm">{k.trend > 0 ? "+" : ""}{k.trend}</Badge>}
              </Group>
            ) : (
              <Text mt={8} size="sm">
                {k.status === "not_connected" ? <>Connectez <Anchor component={Link} to={`/t/${tenantId}/connectors`}>{k.source}</Anchor> pour suivre cet indicateur.</> : "Lancez un audit ou un test IA pour l'alimenter."}
              </Text>
            )}
            <Text size="xs" c="dimmed" mt={6}>{k.note ?? `Source : ${k.source}`}</Text>
          </Card>
        );
      })}
    </SimpleGrid>
  );
}

// ───────────────────────────── Tenant home ─────────────────────────────
export function HomeDashboardPage() {
  const { tenantId, tenant, can } = useTenant();
  const { data: me } = useMe();
  const kpis = useQuery({ queryKey: ["kpis", tenantId], queryFn: () => api<KpiResponse>("/visibility/kpis", { tenantId }) });
  const audits = useQuery({ queryKey: ["v-audits", tenantId], queryFn: () => api<Audit[] | { results: Audit[] }>("/visibility/audits", { tenantId }), enabled: can("seo.read") });
  const recs = useQuery({ queryKey: ["v-recs", tenantId, "proposed"], queryFn: () => api<Recommendation[]>("/visibility/recommendations", { tenantId, query: { status: "proposed" } }), enabled: can("seo.read") });
  const list = Array.isArray(audits.data) ? audits.data : audits.data?.results ?? [];
  const last = list.find((a) => a.status === "succeeded");
  const name = me?.user.email?.split("@")[0] ?? "";
  return (
    <Stack gap="xl">
      <Group justify="space-between" align="flex-end">
        <Stack gap={4}>
          <Title order={1}>Bonjour {name}</Title>
          <Text c="dimmed">{tenant?.name} — visibilité Google, Bing et moteurs IA, en un coup d'œil.</Text>
        </Stack>
        <Group>
          <Button component={Link} to={`/t/${tenantId}/audit`} variant="default" leftSection={<IconRadar size={16} />}>Lancer l'audit</Button>
          <Button component={Link} to={`/t/${tenantId}/visibility/new`} leftSection={<IconPlus size={16} />}>Nouveau programme</Button>
        </Group>
      </Group>
      <KpiGrid data={kpis.data} />
      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, lg: 5 }}>
          <Card h="100%">
            <Text fw={600} mb="xs">Dernier audit</Text>
            {last ? (
              <Stack gap="xs">
                <Group align="baseline" gap={6}><Text className="gi-num" fz={44} fw={600} ff="heading">{last.score ?? "—"}</Text><Text c="dimmed">/100</Text></Group>
                <Progress value={last.score ?? 0} color={(last.score ?? 0) >= 75 ? "signal" : (last.score ?? 0) >= 50 ? "yellow" : "red"} radius="xl" />
                <Text size="sm" c="dimmed">{last.site_findings?.domain} — {formatDate(last.finished_at ?? last.created_at)}</Text>
                <Button component={Link} to={`/t/${tenantId}/visibility/audit/${last.id}`} variant="light" mt="sm">Voir le rapport</Button>
              </Stack>
            ) : (
              <Stack gap="sm" align="flex-start">
                <Text size="sm" c="dimmed">Aucun audit pour l'instant. Indiquez le lien de votre site : l'IA l'analyse, compare vos concurrents et propose un plan d'actions.</Text>
                <Button component={Link} to={`/t/${tenantId}/visibility/new`} leftSection={<IconPlayerPlay size={16} />}>Analyser mon site</Button>
              </Stack>
            )}
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 7 }}>
          <Card h="100%">
            <Group justify="space-between" mb="xs"><Text fw={600}>Actions recommandées en attente</Text><Badge>{recs.data?.length ?? 0}</Badge></Group>
            <Stack gap={6}>
              {(recs.data ?? []).slice(0, 6).map((r) => (
                <Group key={r.id} justify="space-between" wrap="nowrap">
                  <Text size="sm" truncate>{r.title}</Text>
                  <Badge color={PRIORITY[r.priority].color} size="sm">{PRIORITY[r.priority].label}</Badge>
                </Group>
              ))}
              {!recs.data?.length && <Text size="sm" c="dimmed">Rien en attente : toutes les actions proposées ont été traitées.</Text>}
            </Stack>
          </Card>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}

// ───────────────────────────── Programmes list ─────────────────────────────
export function ProgrammesPage() {
  const { tenantId, can } = useTenant();
  const profiles = useQuery({ queryKey: ["v-profiles", tenantId], queryFn: () => api<Profile[] | { results: Profile[] }>("/visibility/profiles", { tenantId }) });
  const audits = useQuery({ queryKey: ["v-audits", tenantId], queryFn: () => api<Audit[] | { results: Audit[] }>("/visibility/audits", { tenantId }) });
  const plist = Array.isArray(profiles.data) ? profiles.data : profiles.data?.results ?? [];
  const alist = Array.isArray(audits.data) ? audits.data : audits.data?.results ?? [];
  return (
    <>
      <PageHeader title="Programmes de visibilité" subtitle="Un programme analyse votre SaaS et vos concurrents, puis exécute le plan validé au rythme choisi."
        actions={can("seo.manage") && <Button component={Link} to={`/t/${tenantId}/visibility/new`} leftSection={<IconPlus size={16} />}>Nouveau programme</Button>} />
      {plist.length === 0 && <Card><Text c="dimmed">Aucun programme. Créez le premier : il suffit du lien de votre site.</Text></Card>}
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {plist.map((p) => {
          const a = alist.find((x) => (x as Audit & { profile_id?: string }).profile_id === p.id);
          return (
            <Card key={p.id}>
              <Group justify="space-between" mb={6}><Text fw={600}>{p.name}</Text>{a && <Badge color={a.status === "succeeded" ? "signal" : a.status === "failed" ? "red" : "aurora"}>{a.status === "succeeded" ? `${a.score ?? "—"}/100` : a.status}</Badge>}</Group>
              <Text size="sm" c="dimmed" truncate>{(p.site_urls ?? []).join(", ")}</Text>
              {a && <Button mt="md" variant="light" component={Link} to={`/t/${tenantId}/visibility/audit/${a.id}`}>Résultats et actions</Button>}
            </Card>
          );
        })}
      </SimpleGrid>
    </>
  );
}

// ───────────────────────────── Assistant popup ─────────────────────────────
interface ChatMsg { role: "user" | "assistant"; content: string }
export function AssistantPopup({ profileId, onAnswers }: { profileId: string | null; onAnswers?: (a: Record<string, string>) => void }) {
  const { tenantId } = useTenant();
  const [opened, setOpened] = useState(false);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [text, setText] = useState("");
  const [progress, setProgress] = useState<{ answered: number; total: number } | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const viewport = useRef<HTMLDivElement>(null);
  const send = useMutation({
    mutationFn: (message: string) => api<{ reply: string; source: string; answered: number; total: number; answers: Record<string, string> }>("/visibility/assistant",
      { method: "POST", tenantId, body: { profile_id: profileId, message, history: msgs, answers } }),
    onSuccess: (r, message) => {
      setMsgs((m) => [...m, ...(message ? [{ role: "user" as const, content: message }] : []), { role: "assistant", content: r.reply }]);
      setProgress({ answered: r.answered, total: r.total });
      setAnswers(r.answers ?? {});
      onAnswers?.(r.answers ?? {});
    },
  });
  useEffect(() => { if (opened && msgs.length === 0 && !send.isPending) send.mutate(""); }, [opened]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { viewport.current?.scrollTo({ top: viewport.current.scrollHeight, behavior: "smooth" }); }, [msgs]);
  return (
    <>
      <Affix position={{ bottom: 24, right: 24 }}>
        <Button size="md" radius="xl" color="aurora" leftSection={<IconMessageChatbot size={18} />} onClick={() => setOpened(true)}>Assistant SEO / GEO</Button>
      </Affix>
      <Drawer opened={opened} onClose={() => setOpened(false)} position="right" size="md" title={<Group gap={8}><ThemeIcon color="aurora" variant="light"><IconSparkles size={16} /></ThemeIcon><Text fw={600}>Assistant SEO / GEO</Text></Group>}>
        <Stack h="calc(100vh - 110px)" gap="sm">
          {progress && <Box><Text size="xs" c="dimmed">Questions essentielles : {progress.answered}/{progress.total}</Text><Progress value={(100 * progress.answered) / progress.total} color="aurora" size="sm" /></Box>}
          <ScrollArea flex={1} viewportRef={viewport}>
            <Stack gap="sm">
              {msgs.map((m, i) => (
                <Paper key={i} p="sm" maw="88%" ml={m.role === "user" ? "auto" : 0} withBorder={m.role === "assistant"}
                  bg={m.role === "user" ? "var(--mantine-color-signal-light)" : undefined}>
                  <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{m.content}</Text>
                </Paper>
              ))}
              {send.isPending && <Group gap={6}><Loader size="xs" color="aurora" /><Text size="xs" c="dimmed">L'assistant réfléchit…</Text></Group>}
            </Stack>
          </ScrollArea>
          {!profileId && <Text size="xs" c="dimmed">Vos réponses seront enregistrées dès que le programme sera créé.</Text>}
          <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) { send.mutate(text.trim()); setText(""); } }}>
            <Group gap="xs" wrap="nowrap">
              <Textarea flex={1} autosize minRows={1} maxRows={4} placeholder="Votre réponse ou votre question…" value={text} onChange={(e) => setText(e.currentTarget.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (text.trim()) { send.mutate(text.trim()); setText(""); } } }} />
              <ActionIcon type="submit" size="lg" color="aurora" aria-label="Envoyer" loading={send.isPending}><IconSend size={18} /></ActionIcon>
            </Group>
          </form>
        </Stack>
      </Drawer>
    </>
  );
}

// ───────────────────────────── Wizard ─────────────────────────────
function ChoiceCard({ active, onClick, icon, title, children }: { active: boolean; onClick: () => void; icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <UnstyledButton onClick={onClick} aria-pressed={active}>
      <Card h="100%" style={{ borderColor: active ? "var(--mantine-color-signal-5)" : undefined, boxShadow: active ? "0 0 0 1px var(--mantine-color-signal-5)" : undefined }}>
        <Group gap="sm" mb={6}>{icon}<Text fw={600}>{title}</Text>{active && <IconCheck size={16} color="var(--mantine-color-signal-5)" />}</Group>
        <Text size="sm" c="dimmed">{children}</Text>
      </Card>
    </UnstyledButton>
  );
}

function ScanAnimation({ step, progress }: { step: string; progress: number }) {
  return (
    <Stack align="center" gap="lg" py="xl">
      <div className="gi-scan" role="img" aria-label="Analyse en cours">
        <span className="gi-scan-dot" style={{ top: "28%", left: "62%" }} />
        <span className="gi-scan-dot" style={{ top: "64%", left: "30%", animationDelay: "0.8s" }} />
        <span className="gi-scan-dot" style={{ top: "40%", left: "22%", animationDelay: "1.6s", background: "var(--gi-ai)", boxShadow: "0 0 12px var(--gi-ai)" }} />
      </div>
      <Stack gap={4} align="center" maw={460}>
        <Text fw={600} ff="heading" ta="center">{step || "Préparation de l'analyse"}</Text>
        <Text size="sm" c="dimmed" ta="center">L'IA explore votre site, relève les mots-clés et le domaine, vérifie robots.txt, sitemaps, canonical, HTTPS, 404, 301, hreflang, Open Graph et JSON-LD, puis analyse vos concurrents.</Text>
      </Stack>
      <Progress value={progress} w={360} radius="xl" color="signal" striped animated aria-label={`${progress}%`} />
    </Stack>
  );
}

export function ProgrammeWizardPage() {
  const { tenantId } = useTenant();
  const navigate = useNavigate();
  const [active, setActive] = useState(0);
  const [kind, setKind] = useState<"standard" | "intelligent">("intelligent");
  const [scope, setScope] = useState<string[]>(["seo", "geo"]);
  const [name, setName] = useState("");
  const [urls, setUrls] = useState<string[]>([""]);
  const [competitors, setCompetitors] = useState<string[]>([""]);
  const [sector, setSector] = useState("");
  const [launched, setLaunched] = useState<{ profile_id: string; audit_id: string } | null>(null);
  const [found, setFound] = useState<Candidate[]>([]);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const discover = useMutation({
    mutationFn: (site: string) => api<DiscoverResult>("/visibility/competitors/discover", { method: "POST", tenantId, body: { site_url: site, name: name || undefined, sector: sector || undefined } }),
    onSuccess: (r) => {
      setFound(r.candidates);
      setPicked(Object.fromEntries(r.candidates.map((c) => [c.name, true])));
      if (!name && r.name) setName(r.name);
    },
  });
  const discoveredFor = useRef("");
  const runDiscovery = () => {
    const first = urls.find((u) => /\.[a-z]{2,}/i.test(u.trim()))?.trim();
    if (first && first !== discoveredFor.current) { discoveredFor.current = first; discover.mutate(first); }
  };
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const launch = useMutation({
    mutationFn: () => api<{ profile_id: string; audit_id: string }>("/visibility/programmes", {
      method: "POST", tenantId,
      body: { name: name || undefined, site_urls: urls.filter((u) => u.trim()),
        competitors: [...found.filter((c) => picked[c.name]).map((c) => ({ name: c.name, url: c.url, source: c.source })), ...competitors.filter((c) => c.trim())], scheduler_kind: kind, scope, sector: sector || undefined, answers },
    }),
    onSuccess: (r) => { setLaunched(r); setActive(3); },
  });
  const prog = useQuery({
    queryKey: ["v-progress", launched?.audit_id], enabled: !!launched,
    queryFn: () => api<{ status: string; progress: number; step: string; error: string | null }>(`/visibility/audits/${launched?.audit_id}/progress`, { tenantId }),
    refetchInterval: (q) => (q.state.data && ["succeeded", "failed"].includes(q.state.data.status) ? false : 1500),
  });
  useEffect(() => { if (prog.data?.status === "succeeded" && launched) navigate(`/t/${tenantId}/visibility/audit/${launched.audit_id}?kind=${kind}`); }, [prog.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const validUrls = urls.some((u) => /\.[a-z]{2,}/i.test(u.trim()));
  const list = (values: string[], set: (v: string[]) => void, placeholder: string, max: number) => (
    <Stack gap="xs">
      {values.map((v, i) => (
        <Group key={i} gap="xs" wrap="nowrap">
          <TextInput flex={1} value={v} placeholder={placeholder} onChange={(e) => set(values.map((x, j) => (j === i ? e.currentTarget.value : x)))}
            onBlur={values === urls ? runDiscovery : undefined} />
          {values.length > 1 && <ActionIcon variant="subtle" color="red" aria-label="Retirer" onClick={() => set(values.filter((_, j) => j !== i))}><IconTrash size={16} /></ActionIcon>}
        </Group>
      ))}
      {values.length < max && <Button variant="subtle" size="xs" leftSection={<IconPlus size={14} />} onClick={() => set([...values, ""])} w="fit-content">Ajouter</Button>}
    </Stack>
  );
  return (
    <>
      <PageHeader title="Nouveau programme de visibilité" subtitle="Objectif : la première place de votre domaine sur Google, Bing et dans les réponses des IA." />
      <Card p="xl">
        <Stepper active={active} onStepClick={(s) => s < 3 && !launched && setActive(s)} color="signal" allowNextStepsSelect={false}>
          <Stepper.Step label="Type" description="Standard ou intelligent">
            <SimpleGrid cols={{ base: 1, md: 2 }} mt="lg">
              <ChoiceCard active={kind === "standard"} onClick={() => setKind("standard")} icon={<ThemeIcon variant="light"><IconCircleDashed size={18} /></ThemeIcon>} title="Programmation standard">
                Les actions validées s'exécutent au rythme fixé (par jour, semaine ou mois), toujours de la même façon.
              </ChoiceCard>
              <ChoiceCard active={kind === "intelligent"} onClick={() => setKind("intelligent")} icon={<ThemeIcon variant="light" color="aurora"><IconBrain size={18} /></ThemeIcon>} title="Programmation intelligente">
                En plus, l'IA ré-analyse chaque semaine votre site et vos concurrents et re-priorise le plan selon les nouveaux constats.
              </ChoiceCard>
            </SimpleGrid>
          </Stepper.Step>
          <Stepper.Step label="Objectifs" description="SEO, GEO, prospection">
            <Stack mt="lg">
              <Checkbox.Group value={scope} onChange={setScope} label="Que doit couvrir le programme ?">
                <Stack mt="xs">
                  <Checkbox value="seo" label="SEO — Google et Bing : technique, mots-clés, contenus, backlinks" />
                  <Checkbox value="geo" label="GEO — présence et citations dans ChatGPT, Claude, Gemini et Perplexity" />
                  <Checkbox value="prospect" label="Prospection — campagnes et veille des conversations à partir de vos thématiques" />
                </Stack>
              </Checkbox.Group>
            </Stack>
          </Stepper.Step>
          <Stepper.Step label="Votre site" description="Liens et concurrents">
            <Grid mt="lg" gutter="xl">
              <Grid.Col span={{ base: 12, md: 6 }}>
                <Stack>
                  <TextInput label="Nom du SaaS" placeholder="Ex. Acme CRM" value={name} onChange={(e) => setName(e.currentTarget.value)} />
                  <Box><Text size="sm" fw={500} mb={4}>Lien(s) de votre site</Text>{list(urls, setUrls, "https://votre-saas.fr", 5)}</Box>
                  <TextInput label="Secteur (facultatif)" placeholder="Ex. CRM pour PME" value={sector} onChange={(e) => setSector(e.currentTarget.value)} />
                </Stack>
              </Grid.Col>
              <Grid.Col span={{ base: 12, md: 6 }}>
                <Group justify="space-between" mb={4}>
                  <Text size="sm" fw={500}>Concurrents à comparer</Text>
                  <Button size="xs" variant="light" leftSection={<IconRadar size={14} />} loading={discover.isPending} disabled={!validUrls}
                    onClick={() => { discoveredFor.current = ""; runDiscovery(); }}>Détecter</Button>
                </Group>
                {discover.isPending && <Group gap={6} mb="xs"><Loader size="xs" /><Text size="xs" c="dimmed">Recherche des concurrents cités sur votre site…</Text></Group>}
                {found.length > 0 && (
                  <Stack gap={6} mb="sm">
                    {found.map((c) => (
                      <Paper key={c.name} p="xs" withBorder>
                        <Group justify="space-between" wrap="nowrap" align="flex-start">
                          <Checkbox checked={!!picked[c.name]} onChange={(e) => { const v = e.currentTarget.checked; setPicked((p) => ({ ...p, [c.name]: v })); }}
                            label={<Text size="sm" fw={500}>{c.name}</Text>} description={c.url || undefined} />
                          <Badge size="xs" color={c.source === "ai_suggested" ? "aurora" : c.source === "site_mentions" ? "signal" : "gray"}>
                            {c.source === "ai_suggested" ? "Suggéré par l'IA" : c.source === "site_mentions" ? "Cité sur votre site" : "Déjà connu"}
                          </Badge>
                        </Group>
                        {c.evidence?.[0] && <Text size="xs" c="dimmed" mt={4} lineClamp={2}>{c.evidence[0]}</Text>}
                      </Paper>
                    ))}
                  </Stack>
                )}
                {discover.data && found.length === 0 && <Text size="xs" c="dimmed" mb="xs">{discover.data.note}</Text>}
                {discover.data && !discover.data.ai_available && <Text size="xs" c="dimmed" mb="xs">Configurez un fournisseur IA (PILOTE → Fournisseurs IA) pour obtenir aussi des suggestions de l'IA.</Text>}
                <Text size="xs" c="dimmed" mb={4}>Ajouter un concurrent (nom ou site)</Text>
                {list(competitors, setCompetitors, "concurrent.com", 5)}
              </Grid.Col>
            </Grid>
          </Stepper.Step>
          <Stepper.Step label="Analyse" description="Scan IA">
            {prog.data?.status === "failed"
              ? <Alert color="red" mt="lg" title="L'analyse a échoué">{prog.data.error}</Alert>
              : <ScanAnimation step={prog.data?.step ?? "Lancement"} progress={prog.data?.progress ?? 2} />}
          </Stepper.Step>
        </Stepper>
        {launch.error && <Alert color="red" mt="md">{errorText(launch.error)}</Alert>}
        {active < 3 && (
          <Group justify="space-between" mt="xl">
            <Button variant="default" disabled={active === 0} onClick={() => setActive((s) => s - 1)}>Retour</Button>
            {active < 2
              ? <Button onClick={() => setActive((s) => s + 1)} disabled={active === 1 && scope.length === 0}>Continuer</Button>
              : <Button leftSection={<IconRadar size={16} />} disabled={!validUrls} loading={launch.isPending} onClick={() => launch.mutate()}>Lancer l'analyse IA</Button>}
          </Group>
        )}
      </Card>
      <AssistantPopup profileId={launched?.profile_id ?? null} onAnswers={setAnswers} />
    </>
  );
}

// ───────────────────────────── Audit results & validation ─────────────────────────────
function ChecksTable({ checks }: { checks: Check[] }) {
  return (
    <Table>
      <Table.Tbody>
        {checks.map((c) => (
          <Table.Tr key={c.code}>
            <Table.Td w={32}>{CHECK_ICON[c.status]}</Table.Td>
            <Table.Td w={260}><Text size="sm" fw={500}>{c.label}</Text></Table.Td>
            <Table.Td><Text size="sm" c="dimmed">{c.detail}</Text></Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

interface Choice { selected: boolean; frequency: string; times: number }
const defaultChoice = (rec: Recommendation): Choice => ({
  selected: rec.status === "proposed" && (rec.priority === "critical" || rec.priority === "high"), frequency: rec.frequency ?? "once", times: rec.times_per_period ?? 1,
});

export function AuditResultPage() {
  const { tenantId, can } = useTenant();
  const { auditId = "" } = useParams();
  const qc = useQueryClient();
  const params = new URLSearchParams(window.location.search);
  const [kind, setKind] = useState<string>(params.get("kind") ?? "standard");
  const [autonomy, setAutonomy] = useState("approval");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [plan, setPlan] = useState<Record<string, PlanChoice>>({});
  const [tab, setTab] = useState<string | null>("actions");
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const q = useQuery({ queryKey: ["v-report", auditId], queryFn: () => api<Report>(`/visibility/audits/${auditId}/report`, { tenantId }) });
  const r = q.data;
  const picked = useMemo(() => (r?.recommendations ?? []).map((rec) => ({ rec, c: choices[rec.id] ?? defaultChoice(rec) }))
    .filter(({ rec, c }) => c.selected && rec.status === "proposed"), [choices, r]);
  const validate = useMutation({
    mutationFn: () => api<{ applied: { status: string }[]; errors: { message: string }[] }>("/visibility/recommendations/accept-bulk", {
      method: "POST", tenantId,
      body: {
        scheduler_kind: kind, autonomy,
        items: (preview.data ?? []).map((p) => {
          const ch = plan[p.id] ?? { mode: "now", frequency: p.frequency, times: p.times_per_period };
          if (!p.recurring_allowed) return { id: p.id, run_now: false };
          return ch.mode === "now" ? { id: p.id, frequency: "once", run_now: true } : { id: p.id, frequency: ch.frequency, times_per_period: ch.times, run_now: false };
        }),
      },
    }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["v-report", auditId] }); void qc.invalidateQueries({ queryKey: ["v-exec", auditId] }); setPreviewOpen(false); setTab("execution"); },
  });
  const preview = useMutation({
    mutationFn: () => api<Preview[]>("/visibility/recommendations/preview", { method: "POST", tenantId, body: { ids: picked.map(({ rec }) => rec.id) } }),
    onSuccess: (rows) => {
      setPlan(Object.fromEntries(rows.map((p) => {
        const freq = choices[p.id]?.frequency ?? p.frequency;
        const recurring = freq !== "once";
        return [p.id, { mode: recurring ? "schedule" : "now", frequency: recurring ? freq : "weekly", times: choices[p.id]?.times ?? p.times_per_period ?? 1 }];
      })));
      setPreviewOpen(true);
    },
  });
  const download = async (asset: Asset) => {
    const res = await api<Response>(`/visibility/assets/${asset.id}/download`, { tenantId, raw: true });
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url; a.download = asset.filename; a.click();
    URL.revokeObjectURL(url);
  };
  const selectedCount = picked.length;
  if (q.isLoading || !r) return <Loader />;
  const a = r.audit;
  const sum = a.ai_summary as Summary;
  const sites = a.site_findings.sites ?? [];
  return (
    <Stack gap="lg">
      <PageHeader title={`Résultats — ${a.profile_name ?? a.site_findings.domain ?? ""}`} subtitle={`Audit du ${formatDate(a.finished_at ?? a.created_at)}`}
        actions={<Button variant="default" leftSection={<IconPrinter size={16} />} onClick={() => window.print()}>Imprimer le rapport</Button>} />
      {a.status !== "succeeded" && <Alert color={a.status === "failed" ? "red" : "blue"}>{a.status === "failed" ? a.error : `${a.step} (${a.progress} %)`}</Alert>}
      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Card h="100%">
            <Group justify="space-between"><Text fw={600}>Score technique</Text><NatureBadge nature="observed" /></Group>
            <Group align="baseline" gap={6} mt="sm"><Text className="gi-num" fz={52} fw={600} ff="heading">{a.score ?? "—"}</Text><Text c="dimmed">/100</Text></Group>
            <Text size="sm" c="dimmed">{sites.reduce((n, s) => n + s.pages_crawled, 0)} pages explorées · {(a.site_findings.keywords ?? []).length} mots-clés relevés</Text>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 8 }}>
          <Card h="100%">
            <Group justify="space-between" mb="xs"><Text fw={600}>Synthèse</Text><NatureBadge nature={sum.source === "ai" ? "ai" : "rules"} /></Group>
            <Text size="sm">{sum.summary}</Text>
            {sum.note && <Text size="xs" c="dimmed" mt="xs">{sum.note}</Text>}
            {sum.quick_wins?.length > 0 && <><Text size="sm" fw={500} mt="sm">Gains rapides</Text><Text size="sm" c="dimmed">{sum.quick_wins.slice(0, 4).join(" · ")}</Text></>}
          </Card>
        </Grid.Col>
      </Grid>
      <Tabs value={tab} onChange={setTab} keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="actions">Plan d'actions ({r.recommendations.length})</Tabs.Tab>
          <Tabs.Tab value="execution">Exécution</Tabs.Tab>
          <Tabs.Tab value="site">Votre site</Tabs.Tab>
          <Tabs.Tab value="competitors">Concurrents</Tabs.Tab>
          <Tabs.Tab value="publish">Quoi publier, où</Tabs.Tab>
          <Tabs.Tab value="files">Fichiers générés ({r.assets.length})</Tabs.Tab>
          <Tabs.Tab value="roadmap">Roadmap</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="actions" pt="md">
          <Card>
            <Group justify="space-between" mb="md" wrap="wrap">
              <Group>
                <SegmentedControl value={kind} onChange={setKind} data={[{ value: "standard", label: "Standard" }, { value: "intelligent", label: "Intelligent" }]} />
                <Select w={260} value={autonomy} onChange={(v) => v && setAutonomy(v)} allowDeselect={false} aria-label="Autonomie"
                  data={[{ value: "approval", label: "Je valide chaque publication" }, { value: "automatic", label: "Automatique" }, { value: "analysis", label: "Analyse seule" }]} />
              </Group>
              {can("seo.manage") && <Button leftSection={<IconCheck size={16} />} disabled={selectedCount === 0} loading={preview.isPending} onClick={() => preview.mutate()}>Valider {selectedCount} action{selectedCount > 1 ? "s" : ""}</Button>}
            </Group>
            {preview.error && <Alert color="red" mb="md">{errorText(preview.error)}</Alert>}
            {validate.data && <Alert color={validate.data.errors.length ? "orange" : "signal"} mb="md">{validate.data.applied.length} action(s) appliquée(s) ou programmée(s).{validate.data.errors.map((e) => ` ${e.message}`).join("")}</Alert>}
            <Table.ScrollContainer minWidth={900}>
              <Table>
                <Table.Thead><Table.Tr><Table.Th w={36} /><Table.Th>Action</Table.Th><Table.Th>Priorité</Table.Th><Table.Th>Application</Table.Th><Table.Th w={260}>Fréquence</Table.Th><Table.Th>État</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {r.recommendations.map((rec) => {
                    const c = choices[rec.id] ?? defaultChoice(rec);
                    const editable = rec.status === "proposed";
                    const set = (patch: Partial<Choice>) => setChoices((p) => ({ ...p, [rec.id]: { ...c, ...patch } }));
                    return (
                      <Table.Tr key={rec.id}>
                        <Table.Td><Checkbox checked={c.selected && editable} disabled={!editable} onChange={(e) => set({ selected: e.currentTarget.checked })} aria-label={rec.title} /></Table.Td>
                        <Table.Td><Text size="sm" fw={500}>{rec.title}</Text>{rec.detail && <Text size="xs" c="dimmed" lineClamp={2}>{rec.detail}</Text>}</Table.Td>
                        <Table.Td><Badge color={PRIORITY[rec.priority].color}>{PRIORITY[rec.priority].label}</Badge></Table.Td>
                        <Table.Td><Text size="xs">{MODE_LABEL[rec.apply_mode] ?? rec.apply_mode}</Text></Table.Td>
                        <Table.Td>
                          {rec.apply_mode === "ai_content" || rec.apply_mode === "auto_connector" ? (
                            <Group gap={6} wrap="nowrap">
                              <NumberInput w={70} size="xs" min={1} max={30} value={c.times} disabled={!editable} onChange={(v) => set({ times: Number(v) || 1 })} aria-label="Nombre de fois" />
                              <Select w={140} size="xs" data={FREQUENCIES} value={c.frequency} disabled={!editable} allowDeselect={false} onChange={(v) => v && set({ frequency: v })} aria-label="Période" />
                            </Group>
                          ) : <Text size="xs" c="dimmed">Une fois</Text>}
                        </Table.Td>
                        <Table.Td><Badge color={rec.status === "scheduled" ? "aurora" : rec.status === "accepted" || rec.status === "applied" ? "signal" : rec.status === "rejected" ? "gray" : "blue"} variant="dot">{rec.status}</Badge></Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Card>
        </Tabs.Panel>
        <Tabs.Panel value="execution" pt="md"><ExecutionPanel auditId={auditId} /></Tabs.Panel>
        <Tabs.Panel value="site" pt="md">
          <Stack>
            {sites.map((s) => (
              <Card key={s.url}>
                <Group justify="space-between" mb="sm"><Text fw={600}>{s.url}</Text><Group gap="xs"><NatureBadge nature="observed" /><Badge>{s.score}/100</Badge></Group></Group>
                <ChecksTable checks={s.checks} />
              </Card>
            ))}
            <Card>
              <Group justify="space-between" mb="sm"><Text fw={600}>Mots-clés relevés sur le site</Text><NatureBadge nature="observed" /></Group>
              <Group gap={6}>{(a.site_findings.keywords ?? []).slice(0, 40).map((k) => <Badge key={k.keyword} variant="outline" color="signal">{k.keyword}</Badge>)}</Group>
            </Card>
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="competitors" pt="md">
          <Stack>
            <SimpleGrid cols={{ base: 1, md: 2 }}>
              {(a.competitor_findings.competitors ?? []).map((c) => (
                <Card key={c.name}>
                  <Group justify="space-between" mb={4}><Text fw={600}>{c.name}</Text>{c.source === "ai_suggested" ? <Badge color="aurora">Suggéré par l'IA</Badge> : <Badge variant="outline">Indiqué par vous</Badge>}</Group>
                  <Text size="xs" c="dimmed" mb="xs">{c.url}</Text>
                  {c.error ? <Text size="sm" c="red">Site injoignable ({c.error})</Text> : (
                    <>
                      <Text size="sm">Score technique : {c.score}/100 · llms.txt : {c.has_llms_txt ? "oui" : "non"} · JSON-LD : {(c.jsonld_types ?? []).join(", ") || "aucun"}</Text>
                      <Group gap={4} mt="xs">{(c.keywords ?? []).slice(0, 12).map((k) => <Badge key={k.keyword} size="xs" variant="light" color="gray">{k.keyword}</Badge>)}</Group>
                    </>
                  )}
                </Card>
              ))}
            </SimpleGrid>
            <Card>
              <Text fw={600} mb="xs">Mots-clés de vos concurrents absents de votre site</Text>
              <Table><Table.Tbody>{(a.competitor_findings.keyword_gap ?? []).map((g) => <Table.Tr key={g.keyword}><Table.Td>{g.keyword}</Table.Td><Table.Td><Text size="sm" c="dimmed">{g.competitors.join(", ")}</Text></Table.Td></Table.Tr>)}</Table.Tbody></Table>
            </Card>
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="publish" pt="md">
          <Grid gutter="lg">
            <Grid.Col span={{ base: 12, md: 6 }}>
              <Card h="100%">
                <Group justify="space-between" mb="xs"><Text fw={600}>Contenus à publier</Text><NatureBadge nature={sum.source === "ai" ? "ai" : "rules"} /></Group>
                <Stack gap={6}>{(sum.what_to_publish ?? []).map((p, i) => <Text key={i} size="sm">• {p.title}{p.channel ? ` — ${p.channel}` : ""}</Text>)}</Stack>
                <Text size="xs" c="dimmed" mt="sm">Articles avec mots-clés, étude et statistiques sourcées, comparatifs et FAQ. Aucun chiffre n'est inventé : une donnée sans source est marquée « à compléter ».</Text>
              </Card>
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <Card h="100%">
                <Text fw={600} mb="xs">Canaux recommandés</Text>
                <Stack gap="xs">{r.channels.map((c) => <Box key={c.code}><Text size="sm" fw={500}>{c.name}</Text><Text size="xs" c="dimmed">{c.why}</Text></Box>)}</Stack>
              </Card>
            </Grid.Col>
          </Grid>
        </Tabs.Panel>
        <Tabs.Panel value="files" pt="md">
          <Card>
            <Text size="sm" c="dimmed" mb="md">Générés à partir de ce qui a été observé sur votre site. À relire, puis à placer à la racine du site (ou dans le &lt;head&gt; pour les balises). Avec un connecteur CMS, Growth IA les publie pour vous.</Text>
            <Table>
              <Table.Tbody>
                {r.assets.map((f) => (
                  <Table.Tr key={f.id}><Table.Td><Text size="sm" fw={500}>{f.filename}</Text></Table.Td><Table.Td><Text size="xs" c="dimmed">{f.asset_type}</Text></Table.Td>
                    <Table.Td ta="right"><Button size="xs" variant="light" leftSection={<IconDownload size={14} />} onClick={() => void download(f)}>Télécharger</Button></Table.Td></Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Card>
        </Tabs.Panel>
        <Tabs.Panel value="roadmap" pt="md"><Roadmap items={r.roadmap} /></Tabs.Panel>
      </Tabs>
      <Modal opened={previewOpen} onClose={() => setPreviewOpen(false)} size="xl" title={<Text fw={600}>Corrections proposées — {preview.data?.length ?? 0} action(s)</Text>}>
        <Stack>
          <Group justify="space-between">
            <Text size="sm" c="dimmed">Vérifiez ce qui sera appliqué, puis choisissez pour chaque action : la lancer tout de suite ou la programmer.</Text>
            <Group gap="xs">
              <Button size="xs" variant="default" onClick={() => setPlan((pl) => Object.fromEntries(Object.entries(pl).map(([k, v]) => [k, { ...v, mode: "now" }])))}>Tout lancer maintenant</Button>
              <Button size="xs" variant="default" onClick={() => setPlan((pl) => Object.fromEntries(Object.entries(pl).map(([k, v]) => [k, { ...v, mode: "schedule" }])))}>Tout programmer</Button>
            </Group>
          </Group>
          {(preview.data ?? []).map((p) => {
            const ch = plan[p.id] ?? { mode: "now", frequency: "weekly", times: 1 };
            const set = (patch: Partial<PlanChoice>) => setPlan((pl) => ({ ...pl, [p.id]: { ...ch, ...patch } }));
            return (
              <Card key={p.id} padding="md">
                <Group justify="space-between" mb="xs" wrap="nowrap" align="flex-start">
                  <Box><Text fw={600} size="sm">{p.title}</Text><Text size="xs" c="dimmed">{MODE_LABEL[p.apply_mode] ?? p.apply_mode}</Text></Box>
                  <Badge color={PRIORITY[p.priority].color}>{PRIORITY[p.priority].label}</Badge>
                </Group>
                <CorrectionView c={p.correction} />
                <Divider my="sm" />
                {p.recurring_allowed ? (
                  <Group gap="sm" wrap="wrap">
                    <SegmentedControl size="xs" value={ch.mode} onChange={(v) => set({ mode: v as PlanChoice["mode"] })}
                      data={[{ value: "now", label: "Lancer maintenant" }, { value: "schedule", label: "Programmer" }]} />
                    {ch.mode === "schedule" && (
                      <Group gap={6} wrap="nowrap">
                        <NumberInput w={70} size="xs" min={1} max={30} value={ch.times} onChange={(v) => set({ times: Number(v) || 1 })} aria-label="Nombre de fois" />
                        <Select w={150} size="xs" allowDeselect={false} value={ch.frequency} onChange={(v) => v && set({ frequency: v })} aria-label="Période"
                          data={FREQUENCIES.filter((f) => f.value !== "once")} />
                      </Group>
                    )}
                  </Group>
                ) : <Badge variant="light" color="signal" leftSection={<IconCheck size={12} />}>Appliquée dès la confirmation</Badge>}
              </Card>
            );
          })}
          {validate.error && <Alert color="red">{errorText(validate.error)}</Alert>}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setPreviewOpen(false)}>Annuler</Button>
            <Button leftSection={<IconCheck size={16} />} loading={validate.isPending} onClick={() => validate.mutate()}>Confirmer</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

function CorrectionView({ c }: { c: Correction }) {
  if (c.kind === "file") {
    return (
      <Stack gap={6}>
        <Group gap="xs"><Text size="xs" fw={500}>{c.filename}</Text><NatureBadge nature="observed" />{c.cms_available && <Badge size="xs" color="signal">Publication via CMS</Badge>}</Group>
        <Code block style={{ maxHeight: 220, overflow: "auto", fontSize: 12 }}>{c.content}{c.truncated ? "\n…" : ""}</Code>
        <Text size="xs" c="dimmed">{c.how}</Text>
      </Stack>
    );
  }
  if (c.kind === "content") {
    return (
      <Stack gap={6}>
        <Group gap="xs"><Badge size="xs" color="aurora">{c.content_type}</Badge>{c.keyword && <Badge size="xs" variant="outline">mot-clé : {c.keyword}</Badge>}<Badge size="xs" variant="outline">{c.channel}</Badge></Group>
        {c.objective && <Text size="xs">{c.objective}</Text>}
        <Stack gap={2}>{(c.plan ?? []).map((x) => <Text key={x} size="xs">• {x}</Text>)}</Stack>
        <Text size="xs" c="dimmed">{c.how}</Text>
      </Stack>
    );
  }
  return <Text size="xs">{c.how}</Text>;
}

const STATE_COLOR: Record<Execution["state"], string> = {
  ready: "signal", planned: "gray", queued: "blue", running: "aurora", succeeded: "signal", awaiting_approval: "yellow", failed: "red", cancelled: "gray",
};

function ExecutionPanel({ auditId }: { auditId: string }) {
  const { tenantId, can } = useTenant();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["v-exec", auditId],
    queryFn: () => api<Execution[]>("/visibility/recommendations/execution", { tenantId, query: { audit_id: auditId } }),
    refetchInterval: (query) => ((query.state.data ?? []).some((x) => x.state === "queued" || x.state === "running") ? 2000 : 15000),
  });
  const run = useMutation({
    mutationFn: (id: string) => api(`/visibility/recommendations/${id}/run-now`, { method: "POST", tenantId }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["v-exec", auditId] }),
  });
  const rows = q.data ?? [];
  const done = rows.filter((r) => ["ready", "succeeded", "awaiting_approval"].includes(r.state)).length;
  const active = rows.filter((r) => r.state === "queued" || r.state === "running").length;
  if (q.isLoading) return <Loader size="sm" />;
  if (!rows.length) return <Card><Text c="dimmed" size="sm">Aucune action validée pour l'instant. Cochez des actions dans le plan puis cliquez sur « Valider ».</Text></Card>;
  return (
    <Stack>
      <Card>
        <Group justify="space-between" mb="xs">
          <Text fw={600}>Avancement global</Text>
          <Group gap="xs">{active > 0 && <Loader size="xs" color="aurora" />}<Text size="sm" className="gi-num">{done}/{rows.length} terminée(s){active ? ` · ${active} en cours` : ""}</Text></Group>
        </Group>
        <Progress value={(100 * done) / rows.length} color="signal" radius="xl" size="lg" striped={active > 0} animated={active > 0} />
      </Card>
      {run.error && <Alert color="red">{errorText(run.error)}</Alert>}
      <Card>
        <Table.ScrollContainer minWidth={820}>
          <Table>
            <Table.Thead><Table.Tr><Table.Th>Action</Table.Th><Table.Th w={260}>Progression</Table.Th><Table.Th>Prochaine exécution</Table.Th><Table.Th /></Table.Tr></Table.Thead>
            <Table.Tbody>
              {rows.map((r) => (
                <Table.Tr key={r.id}>
                  <Table.Td>
                    <Text size="sm" fw={500}>{r.title}</Text>
                    <Text size="xs" c="dimmed">{MODE_LABEL[r.apply_mode] ?? r.apply_mode}{r.frequency && r.frequency !== "once" ? ` · ${r.times_per_period ?? 1}× ${FREQUENCIES.find((f) => f.value === r.frequency)?.label.toLowerCase() ?? r.frequency}` : r.scheduler_id ? " · une fois" : ""}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Progress value={r.progress} color={STATE_COLOR[r.state]} radius="xl" striped={r.state === "running" || r.state === "queued"} animated={r.state === "running"} />
                    <Group gap={6} mt={4} wrap="nowrap">
                      <Badge size="xs" color={STATE_COLOR[r.state]} variant="dot">{r.label}</Badge>
                      {r.state === "awaiting_approval" && <Anchor size="xs" component={Link} to={`/t/${tenantId}/approvals`}>Valider la publication</Anchor>}
                      {r.content_id && <Anchor size="xs" component={Link} to={`/t/${tenantId}/content`}>Voir le contenu</Anchor>}
                    </Group>
                  </Table.Td>
                  <Table.Td><Text size="xs" c="dimmed">{r.next_run_at ? formatDate(r.next_run_at) : r.state === "ready" ? "—" : "Aucune"}</Text></Table.Td>
                  <Table.Td ta="right">
                    {r.can_run_now && can("seo.manage") && (
                      <Button size="xs" variant="light" leftSection={<IconPlayerPlay size={14} />} loading={run.isPending && run.variables === r.id}
                        onClick={() => run.mutate(r.id)}>Exécuter maintenant</Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Card>
    </Stack>
  );
}

function Roadmap({ items }: { items: RoadmapItem[] }) {
  const cols: { key: RoadmapItem["phase"]; label: string; hint: string }[] = [
    { key: "now", label: "Maintenant", hint: "Bloquant pour l'indexation ou la mesure" }, { key: "next", label: "Ensuite", hint: "Fort impact sur la visibilité" }, { key: "later", label: "Plus tard", hint: "Consolidation et notoriété" },
  ];
  return (
    <SimpleGrid cols={{ base: 1, md: 3 }}>
      {cols.map((c) => (
        <Card key={c.key}>
          <Text fw={600}>{c.label}</Text><Text size="xs" c="dimmed" mb="sm">{c.hint}</Text>
          <Stack gap="xs">
            {items.filter((i) => i.phase === c.key).map((i) => (
              <Paper key={i.id} p="sm" withBorder>
                <Group justify="space-between" wrap="nowrap" align="flex-start"><Text size="sm">{i.title}</Text><Badge size="xs" color={i.status === "done" ? "signal" : i.status === "in_progress" ? "aurora" : "gray"}>{i.status}</Badge></Group>
                <Text size="xs" c="dimmed">{i.area}</Text>
              </Paper>
            ))}
          </Stack>
        </Card>
      ))}
    </SimpleGrid>
  );
}

// ───────────────────────────── Tenant technical audit ─────────────────────────────
const AXES = [
  "Identifier les problèmes SEO et les opportunités de référencement",
  "Améliorer la visibilité sur Google et Bing",
  "Mesurer la présence dans ChatGPT, Claude, Gemini et Perplexity",
  "Générer des contenus optimisés",
  "Publier et planifier avec un niveau d'autonomie configurable",
  "Mesurer l'impact sur le trafic, les prospects et les conversions",
];

export function TenantAuditPage() {
  const { tenantId, can } = useTenant();
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const audits = useQuery({ queryKey: ["v-audits", tenantId], queryFn: () => api<Audit[] | { results: Audit[] }>("/visibility/audits", { tenantId }) });
  const list = Array.isArray(audits.data) ? audits.data : audits.data?.results ?? [];
  const run = useMutation({
    mutationFn: () => api<{ audit_ids: string[] }>("/visibility/audits/tenant", { method: "POST", tenantId, body: url ? { site_urls: [url] } : {} }),
    onSuccess: () => void audits.refetch(),
  });
  const running = list.find((a) => a.status === "running" || a.status === "queued");
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => void audits.refetch(), 2000);
    return () => window.clearInterval(id);
  }, [running?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Stack gap="lg">
      <PageHeader title="Audit technique & roadmap" subtitle="Analyse automatique de vos sites et de ceux de vos concurrents, rapport complet et roadmap priorisée." />
      <Grid gutter="lg">
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Card h="100%">
            <Text fw={600} mb="sm">Ce que l'audit couvre</Text>
            <Stack gap={8}>{AXES.map((x, i) => <Group key={x} gap="sm" wrap="nowrap"><ThemeIcon size="sm" radius="xl" variant="light">{i + 1}</ThemeIcon><Text size="sm">{x}</Text></Group>)}</Stack>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Card h="100%">
            {running ? <ScanAnimation step={running.step} progress={running.progress} /> : (
              <Stack>
                <Text fw={600}>Lancer l'audit</Text>
                <Text size="sm" c="dimmed">L'audit porte sur les sites de vos programmes. S'il n'y en a pas encore, indiquez le site de votre SaaS.</Text>
                <TextInput placeholder="https://votre-saas.fr" value={url} onChange={(e) => setUrl(e.currentTarget.value)} />
                {run.error && <Alert color="red">{errorText(run.error)}</Alert>}
                <Button leftSection={<IconRadar size={16} />} disabled={!can("seo.manage")} loading={run.isPending} onClick={() => run.mutate()}>Lancer l'audit</Button>
              </Stack>
            )}
          </Card>
        </Grid.Col>
      </Grid>
      <Card>
        <Text fw={600} mb="sm">Rapports</Text>
        <Table>
          <Table.Thead><Table.Tr><Table.Th>Date</Table.Th><Table.Th>Type</Table.Th><Table.Th>État</Table.Th><Table.Th>Score</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {list.map((a) => (
              <Table.Tr key={a.id}>
                <Table.Td>{formatDate(a.created_at)}</Table.Td><Table.Td>{a.audit_type === "tenant_full" ? "Audit complet" : "Programme"}</Table.Td>
                <Table.Td><Badge variant="dot" color={a.status === "succeeded" ? "signal" : a.status === "failed" ? "red" : "aurora"}>{a.status}</Badge></Table.Td>
                <Table.Td className="gi-num">{a.score ?? "—"}</Table.Td>
                <Table.Td ta="right">{a.status === "succeeded" && <Button size="xs" variant="light" onClick={() => navigate(`/t/${tenantId}/visibility/audit/${a.id}`)}>Rapport complet</Button>}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}

// ───────────────────────────── AI Visibility Intelligence ─────────────────────────────
interface AiDash { engines: { engine: string; responses: number; mentions: number; citations: number; presence_rate: number | null; last_test: string | null }[]; responses: number; mention_rate: number | null; citations: number; questions: { id: string; question: string; intent: string | null; source: string; is_active: boolean }[]; engines_without_api: string[]; disclaimer: string }

export function AiVisibilityPage() {
  const { tenantId, can } = useTenant();
  const qc = useQueryClient();
  const d = useQuery({ queryKey: ["ai-vis", tenantId], queryFn: () => api<AiDash>("/visibility/ai", { tenantId }) });
  const profiles = useQuery({ queryKey: ["v-profiles", tenantId], queryFn: () => api<Profile[] | { results: Profile[] }>("/visibility/profiles", { tenantId }) });
  const plist = Array.isArray(profiles.data) ? profiles.data : profiles.data?.results ?? [];
  const [question, setQuestion] = useState("");
  const seed = useMutation({ mutationFn: (pid: string) => api("/visibility/ai", { method: "POST", tenantId, body: { profile_id: pid } }), onSuccess: () => void qc.invalidateQueries({ queryKey: ["ai-vis", tenantId] }) });
  const add = useMutation({
    mutationFn: () => api("/visibility/questions", { method: "POST", tenantId, body: { question, source: "user", profile_id: plist[0]?.id ?? null, intent: "discovery" } }),
    onSuccess: () => { setQuestion(""); void qc.invalidateQueries({ queryKey: ["ai-vis", tenantId] }); },
  });
  const data = d.data;
  return (
    <Stack gap="lg">
      <PageHeader title="AI Visibility Intelligence" subtitle="Votre présence dans les réponses des moteurs IA, mesurée sur des tests réellement exécutés." />
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <Card><Group justify="space-between"><Text size="sm" c="dimmed">AI mention rate</Text><NatureBadge nature={data?.responses ? "observed" : "no_data"} /></Group><Text className="gi-num" fz={36} fw={600} ff="heading">{data?.mention_rate ?? "—"}{data?.mention_rate !== null && data?.mention_rate !== undefined ? "%" : ""}</Text></Card>
        <Card><Group justify="space-between"><Text size="sm" c="dimmed">Citations détectées</Text><NatureBadge nature={data?.responses ? "observed" : "no_data"} /></Group><Text className="gi-num" fz={36} fw={600} ff="heading">{data?.citations ?? 0}</Text></Card>
        <Card><Text size="sm" c="dimmed">Réponses IA analysées (90 j)</Text><Text className="gi-num" fz={36} fw={600} ff="heading">{data?.responses ?? 0}</Text></Card>
      </SimpleGrid>
      <Card>
        <Text fw={600} mb="sm">Présence par moteur</Text>
        {data?.engines.length ? (
          <Stack gap="sm">
            {data.engines.map((e) => (
              <Box key={e.engine}>
                <Group justify="space-between"><Text size="sm">{e.engine}</Text><Text size="sm" className="gi-num">{e.presence_rate ?? 0} % <Text span c="dimmed" size="xs">({e.mentions}/{e.responses})</Text></Text></Group>
                <Progress value={e.presence_rate ?? 0} color="signal" radius="xl" />
              </Box>
            ))}
          </Stack>
        ) : <Text size="sm" c="dimmed">Aucun test exécuté pour l'instant. Construisez la bibliothèque de questions, puis lancez les tests depuis le module GEO (fournisseurs IA configurés par le PILOTE).</Text>}
        <Text size="xs" c="dimmed" mt="md">{data?.disclaimer} Sans API autorisée, non mesurés : {data?.engines_without_api.join(", ")}.</Text>
      </Card>
      <Card>
        <Group justify="space-between" mb="sm">
          <Text fw={600}>Bibliothèque de questions</Text>
          {can("geo.manage") && plist[0] && <Button size="xs" variant="light" color="aurora" leftSection={<IconRobot size={14} />} loading={seed.isPending} onClick={() => { if (plist[0]) seed.mutate(plist[0].id); }}>Générer les questions du secteur</Button>}
        </Group>
        {can("geo.manage") && (
          <Group mb="md" wrap="nowrap"><TextInput flex={1} placeholder="Ex. Quel est le meilleur CRM pour une PME ?" value={question} onChange={(e) => setQuestion(e.currentTarget.value)} />
            <Button disabled={!question.trim() || !plist[0]} onClick={() => add.mutate()} loading={add.isPending}>Ajouter</Button></Group>
        )}
        <Table><Table.Tbody>{(data?.questions ?? []).map((q) => <Table.Tr key={q.id}><Table.Td>{q.question}</Table.Td><Table.Td><Badge size="xs" variant="outline">{q.intent ?? "—"}</Badge></Table.Td><Table.Td><Text size="xs" c="dimmed">{q.source}</Text></Table.Td></Table.Tr>)}</Table.Tbody></Table>
      </Card>
      <Divider />
      <Tooltip label="Les résultats varient selon la question, la langue, la localisation et le moment du test."><Text size="xs" c="dimmed" w="fit-content">Méthode : questions sectorielles → tests via API → mentions et citations → fréquence et évolution → comparaison concurrents → actions correctives.</Text></Tooltip>
    </Stack>
  );
}
