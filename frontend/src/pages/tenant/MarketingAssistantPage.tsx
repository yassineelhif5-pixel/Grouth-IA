import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { IconCheck, IconMessageChatbot, IconSparkles } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/services/api";
import { useTenant } from "@/hooks/useMe";

type Conversation = { id: string; title: string; status: string };
type Message = { id: string; role: "user" | "assistant" | "system"; content: string };
type Strategy = {
  id: string;
  title: string;
  summary: string;
  status: string;
  strategy: {
    objectives?: string[];
    target_audiences?: string[];
    editorial_pillars?: string[];
    articles?: { title: string; primary_keyword?: string; secondary_keywords?: string[]; angle?: string }[];
    questions?: string[];
    assumptions?: string[];
    channels?: string[];
  };
};

export function MarketingAssistantPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [strategy, setStrategy] = useState<Strategy | null>(null);
  const [editingStrategy, setEditingStrategy] = useState(false);
  const [strategyTitle, setStrategyTitle] = useState("");
  const [strategySummary, setStrategySummary] = useState("");
  const [strategyEditor, setStrategyEditor] = useState<Strategy["strategy"] | null>(null);
  const conversations = useQuery({
    queryKey: ["marketing-conversations", tenantId],
    queryFn: () => api<Conversation[]>("/marketing/conversations", { tenantId }),
  });
  const messages = useQuery({
    queryKey: ["marketing-chat", tenantId, conversationId],
    enabled: !!conversationId,
    queryFn: () => api<Message[]>("/marketing/chat", { tenantId, query: { conversation_id: conversationId } }),
  });
  const chat = useMutation({
    mutationFn: (payload: { conversation_id?: string; message: string }) =>
      api<{ conversation_id: string; answer: string }>("/marketing/chat", { method: "POST", tenantId, body: payload }),
    onSuccess: async (result) => {
      setConversationId(result.conversation_id);
      setMessage("");
      await qc.invalidateQueries({ queryKey: ["marketing-chat", tenantId, result.conversation_id] });
      await qc.invalidateQueries({ queryKey: ["marketing-conversations", tenantId] });
    },
  });
  const propose = useMutation({
    mutationFn: () => api<Strategy>("/marketing/strategies", {
      method: "POST", tenantId, body: { conversation_id: conversationId },
    }),
    onSuccess: (result) => {
      setStrategy(result);
      setStrategyTitle(result.title);
      setStrategySummary(result.summary);
      setStrategyEditor(result.strategy);
      setEditingStrategy(false);
      qc.invalidateQueries({ queryKey: ["marketing-strategies", tenantId] });
    },
  });
  const saveStrategy = useMutation({
    mutationFn: () => api<Strategy>("/marketing/strategies/" + strategy?.id, {
      method: "PUT", tenantId, body: { title: strategyTitle, summary: strategySummary, strategy: strategyEditor },
    }),
    onSuccess: (result) => {
      setStrategy(result);
      setStrategyTitle(result.title);
      setStrategySummary(result.summary);
      setStrategyEditor(result.strategy);
      setEditingStrategy(false);
    },
  });
  const campaign = useMutation({
    mutationFn: () => api<{ id: string; articles_created: number; duplicates_skipped: number; note: string }>("/marketing/campaigns", {
      method: "POST", tenantId, body: { strategy_id: strategy?.id },
    }),
  });
  const approve = useMutation({
    mutationFn: () => api<{ status: string }>("/marketing/strategies/" + strategy?.id + "/approve", { method: "POST", tenantId, body: {} }),
    onSuccess: (result) => setStrategy((old) => old ? { ...old, status: result.status } : old),
  });

  const submit = () => {
    if (!message.trim() || chat.isPending) return;
    chat.mutate({ ...(conversationId ? { conversation_id: conversationId } : {}), message: message.trim() });
  };

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <div>
          <Title order={2}>Assistant Marketing IA</Title>
          <Text size="sm" c="dimmed">Décrivez librement votre activité et vos objectifs. L'assistant construit la stratégie avec vous.</Text>
        </div>
        <Badge color="teal" variant="light">Conversation-first</Badge>
      </Group>
      <Alert color="blue" title="Votre site n'est pas analysé automatiquement">
        La stratégie est fondée sur vos réponses et votre profil marketing. L'URL du site est facultative et ne déclenche aucun crawl.
      </Alert>
      <Group align="flex-start" grow>
        <Card withBorder radius="md" maw={260}>
          <Stack gap="sm">
            <Text fw={600}>Conversations</Text>
            <Button variant="light" leftSection={<IconMessageChatbot size={16} />} onClick={() => { setConversationId(null); setStrategy(null); }}>
              Nouvelle conversation
            </Button>
            {conversations.isLoading ? <Loader size="sm" /> : conversations.data?.map((item) => (
              <Button key={item.id} variant={conversationId === item.id ? "light" : "subtle"} color="gray" justify="start"
                onClick={() => { setConversationId(item.id); setStrategy(null); }}>
                {item.title}
              </Button>
            ))}
          </Stack>
        </Card>
        <Stack style={{ flex: 1 }} gap="md">
          <Card withBorder radius="md">
            <Stack gap="md">
              <ScrollArea h={360} offsetScrollbars>
                <Stack gap="sm" pr="sm">
                  {!conversationId && <Paper p="md" radius="md" bg="var(--mantine-color-blue-light)">
                    <Text fw={600}>Bonjour ! Commençons par votre activité.</Text>
                    <Text size="sm">Que propose votre entreprise, à qui vous adressez-vous et quel résultat marketing souhaitez-vous obtenir ? Vous pouvez répondre naturellement, sans formulaire.</Text>
                  </Paper>}
                  {messages.data?.map((item) => (
                    <Paper key={item.id} p="sm" radius="md" bg={item.role === "user" ? "var(--mantine-color-gray-light)" : "var(--mantine-color-teal-light)"}>
                      <Text size="xs" fw={700} c="dimmed" mb={4}>{item.role === "user" ? "VOUS" : "ASSISTANT MARKETING"}</Text>
                      <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{item.content}</Text>
                    </Paper>
                  ))}
                  {chat.isPending && <Group gap="xs"><Loader size="xs" /><Text size="sm" c="dimmed">L'assistant réfléchit…</Text></Group>}
                </Stack>
              </ScrollArea>
              <Textarea
                value={message}
                onChange={(event) => setMessage(event.currentTarget.value)}
                placeholder="Ex. Nous sommes une ESN spécialisée dans la GED et nous voulons attirer des PME en France…"
                minRows={3}
                autosize
                onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }}
              />
              <Group justify="space-between">
                <Text size="xs" c="dimmed">Entrée pour envoyer · Maj + Entrée pour une nouvelle ligne</Text>
                <Button leftSection={<IconMessageChatbot size={16} />} onClick={submit} loading={chat.isPending} disabled={!message.trim()}>
                  Envoyer
                </Button>
              </Group>
              {chat.isError && <Alert color="red">{chat.error instanceof Error ? chat.error.message : "Erreur pendant l'envoi."}</Alert>}
            </Stack>
          </Card>
          <Group justify="space-between">
            <div>
              <Title order={4}>Proposition éditoriale</Title>
              <Text size="xs" c="dimmed">Générez un récapitulatif à partir de la conversation. Rien n'est publié automatiquement.</Text>
            </div>
            <Button variant="light" leftSection={<IconSparkles size={16} />} onClick={() => propose.mutate()}
              disabled={!conversationId || !(messages.data?.some((m) => m.role === "user"))} loading={propose.isPending}>
              Proposer une stratégie
            </Button>
          </Group>
          {propose.isError && <Alert color="red">{propose.error instanceof Error ? propose.error.message : "Impossible de générer la stratégie."}</Alert>}
          {strategy && <Card withBorder radius="md">
            <Stack gap="sm">
              <Group justify="space-between">
                <Title order={4}>{strategy.title}</Title>
                <Badge color={strategy.status === "approved" ? "green" : "yellow"}>{strategy.status}</Badge>
              </Group>
              {editingStrategy && strategyEditor ? (
                <Stack gap="sm">
                  <TextInput label="Titre de la stratégie" value={strategyTitle} onChange={(e) => setStrategyTitle(e.currentTarget.value)} />
                  <Textarea label="Récapitulatif" value={strategySummary} onChange={(e) => setStrategySummary(e.currentTarget.value)} minRows={3} />
                  <Text fw={600} size="sm">Modifier les articles et mots-clés</Text>
                  {strategyEditor.articles?.map((article, index) => (
                    <Paper key={index} withBorder p="sm" radius="sm">
                      <TextInput label="Titre" value={article.title} onChange={(e) => setStrategyEditor((old) => old ? ({
                        ...old, articles: (old.articles ?? []).map((item, i) => i === index ? { ...item, title: e.currentTarget.value } : item),
                      }) : old)} />
                      <TextInput mt="xs" label="Mot-clé principal" value={article.primary_keyword ?? ""} onChange={(e) => setStrategyEditor((old) => old ? ({
                        ...old, articles: (old.articles ?? []).map((item, i) => i === index ? { ...item, primary_keyword: e.currentTarget.value } : item),
                      }) : old)} />
                    </Paper>
                  ))}
                  <Group justify="flex-end">
                    <Button variant="default" onClick={() => { setEditingStrategy(false); setStrategyEditor(strategy.strategy); setStrategyTitle(strategy.title); setStrategySummary(strategy.summary); }}>Annuler</Button>
                    <Button onClick={() => saveStrategy.mutate()} loading={saveStrategy.isPending}>Enregistrer les modifications</Button>
                  </Group>
                  {saveStrategy.isError && <Alert color="red">{saveStrategy.error instanceof Error ? saveStrategy.error.message : "Erreur de sauvegarde."}</Alert>}
                </Stack>
              ) : (
                <>
                  <Text size="sm">{strategy.summary}</Text>
                  {strategy.strategy.objectives?.length ? <div><Text fw={600} size="sm">Objectifs</Text><Text size="sm">{strategy.strategy.objectives.join(" · ")}</Text></div> : null}
                  {strategy.strategy.target_audiences?.length ? <div><Text fw={600} size="sm">Publics cibles</Text><Text size="sm">{strategy.strategy.target_audiences.join(" · ")}</Text></div> : null}
                  {strategy.strategy.editorial_pillars?.length ? <div><Text fw={600} size="sm">Piliers éditoriaux</Text><Text size="sm">{strategy.strategy.editorial_pillars.join(" · ")}</Text></div> : null}
                  <Stack gap="xs">
                    <Text fw={600} size="sm">Articles proposés</Text>
                    {strategy.strategy.articles?.map((article, index) => (
                      <Paper key={index} withBorder p="sm" radius="sm">
                        <Text fw={600} size="sm">{article.title}</Text>
                        {article.angle && <Text size="xs" c="dimmed">{article.angle}</Text>}
                        <Text size="xs" mt={4}>Mot-clé principal : <b>{article.primary_keyword || "À définir"}</b></Text>
                        {article.secondary_keywords?.length ? <Text size="xs" c="dimmed">Secondaires : {article.secondary_keywords.join(", ")}</Text> : null}
                      </Paper>
                    ))}
                  </Stack>
                  {strategy.strategy.questions?.length ? <Alert color="yellow" title="Points à préciser"><Text size="sm">{strategy.strategy.questions.join(" · ")}</Text></Alert> : null}
                  <Group justify="flex-end">
                    {strategy.status === "proposed" && <Button variant="default" onClick={() => { setEditingStrategy(true); setStrategyEditor(strategy.strategy); setStrategyTitle(strategy.title); setStrategySummary(strategy.summary); }}>Modifier la proposition</Button>}
                    {strategy.status === "proposed" && <Button color="teal" leftSection={<IconCheck size={16} />} onClick={() => approve.mutate()} loading={approve.isPending}>Approuver la stratégie</Button>}
                    {strategy.status === "approved" && <Button onClick={() => campaign.mutate()} loading={campaign.isPending}>Créer le calendrier éditorial</Button>}
                  </Group>
                </>
              )}
              {campaign.data && <Alert color="green" title="Calendrier préparé">{campaign.data.articles_created} articles ajoutés · {campaign.data.duplicates_skipped} doublons ignorés. {campaign.data.note}</Alert>}
              {campaign.isError && <Alert color="red">{campaign.error instanceof Error ? campaign.error.message : "Erreur de création du calendrier."}</Alert>}
              {approve.isError && <Alert color="red">{approve.error instanceof Error ? approve.error.message : "Erreur d'approbation."}</Alert>}
            </Stack>
          </Card>}
        </Stack>
      </Group>
    </Stack>
  );
}
