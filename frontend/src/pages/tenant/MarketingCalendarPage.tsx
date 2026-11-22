import { Alert, Badge, Button, Card, Group, Loader, Paper, Select, Stack, Table, Text, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/services/api";
import { useTenant } from "@/hooks/useMe";

type EditorialArticle = {
  id: string;
  title: string;
  primary_keyword: string;
  status: string;
  planned_for: string | null;
  published_url: string | null;
  content_id?: string | null;
  generation_attempts?: number;
  generation_error?: string | null;
};
type Campaign = {
  id: string;
  name: string;
  status: string;
  timezone: string;
  generation_time: string;
  publish_requires_approval: boolean;
  generation_enabled: boolean;
  content_project_id: string | null;
  content_project_name: string | null;
  starts_on: string | null;
  ends_on: string | null;
  article_count: number;
  articles: EditorialArticle[];
};
type ContentProject = { id: string; name: string; product_id: string; status: string };

export function MarketingCalendarPage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const [projectByCampaign, setProjectByCampaign] = useState<Record<string, string>>({});
  const query = useQuery({
    queryKey: ["marketing-campaigns", tenantId],
    queryFn: () => api<Campaign[]>("/marketing/campaigns", { tenantId }),
    refetchInterval: 30000,
  });
  const projects = useQuery({
    queryKey: ["marketing-content-projects", tenantId],
    queryFn: () => api<ContentProject[]>("/marketing/content-projects", { tenantId }),
  });
  const activate = useMutation({
    mutationFn: ({ campaignId, projectId }: { campaignId: string; projectId: string }) =>
      api("/marketing/campaigns/" + campaignId + "/activate", {
        method: "POST", tenantId, body: { content_project_id: projectId },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["marketing-campaigns", tenantId] }),
  });
  const pause = useMutation({
    mutationFn: (campaignId: string) => api("/marketing/campaigns/" + campaignId + "/pause", {
      method: "POST", tenantId, body: {},
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["marketing-campaigns", tenantId] }),
  });
  const projectOptions = (projects.data ?? []).map((p) => ({ value: p.id, label: p.name }));

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Calendrier éditorial</Title>
        <Text size="sm" c="dimmed">Activez une campagne pour générer automatiquement des brouillons dans Content Studio, selon le fuseau horaire du tenant.</Text>
      </div>
      <Alert color="blue" title="Génération automatique, publication manuelle">
        Le scheduler vérifie les campagnes chaque minute et lance la génération à partir de 00:00 (heure locale). Les contenus restent des brouillons. Aucun article n'est approuvé, publié ou partagé automatiquement.
      </Alert>
      {query.isLoading && <Loader />}
      {query.isError && <Alert color="red">{query.error instanceof Error ? query.error.message : "Erreur de chargement."}</Alert>}
      {projects.isError && <Alert color="red">{projects.error instanceof Error ? projects.error.message : "Impossible de charger les projets Content Studio."}</Alert>}
      {!query.isLoading && !query.data?.length && <Paper withBorder p="lg"><Text c="dimmed">Aucune campagne pour le moment. Échangez avec l'assistant marketing, puis approuvez une stratégie pour préparer votre calendrier.</Text></Paper>}
      {query.data?.map((campaign) => (
        <Card key={campaign.id} withBorder radius="md">
          <Stack gap="sm">
            <Group justify="space-between">
              <Title order={4}>{campaign.name}</Title>
              <Badge color={campaign.status === "active" ? "green" : campaign.status === "paused" ? "orange" : "gray"}>{campaign.status}</Badge>
            </Group>
            <Group gap="lg">
              <Text size="xs" c="dimmed">{campaign.article_count} articles</Text>
              <Text size="xs" c="dimmed">Génération : {campaign.generation_time} ({campaign.timezone})</Text>
              <Text size="xs" c="dimmed">Approbation avant publication : oui</Text>
              {campaign.content_project_name && <Text size="xs" c="dimmed">Projet : {campaign.content_project_name}</Text>}
            </Group>
            {campaign.status !== "active" ? (
              <Group align="end">
                <Select
                  label="Projet Content Studio de destination"
                  placeholder={projects.isLoading ? "Chargement des projets…" : "Sélectionner un projet"}
                  data={projectOptions}
                  value={projectByCampaign[campaign.id] ?? campaign.content_project_id}
                  onChange={(value) => setProjectByCampaign((old) => ({ ...old, [campaign.id]: value ?? "" }))}
                  searchable
                  clearable
                  style={{ flex: 1 }}
                  disabled={projects.isLoading || projectOptions.length === 0}
                />
                <Button
                  onClick={() => activate.mutate({ campaignId: campaign.id, projectId: projectByCampaign[campaign.id] ?? campaign.content_project_id ?? "" })}
                  loading={activate.isPending && activate.variables?.campaignId === campaign.id}
                  disabled={!(projectByCampaign[campaign.id] ?? campaign.content_project_id) || projectOptions.length === 0}
                >
                  Activer la génération
                </Button>
              </Group>
            ) : (
              <Group justify="space-between">
                <Text size="sm" c="teal">Génération des brouillons activée</Text>
                <Button variant="light" color="orange" onClick={() => pause.mutate(campaign.id)}
                  loading={pause.isPending && pause.variables === campaign.id}>Mettre en pause</Button>
              </Group>
            )}
            {projects.data?.length === 0 && campaign.status !== "active" && <Alert color="yellow">Créez d'abord un projet dans Content Studio pour activer la génération de cette campagne.</Alert>}
            {activate.isError && activate.variables?.campaignId === campaign.id && <Alert color="red">{activate.error instanceof Error ? activate.error.message : "Activation impossible."}</Alert>}
            {pause.isError && pause.variables === campaign.id && <Alert color="red">{pause.error instanceof Error ? pause.error.message : "Mise en pause impossible."}</Alert>}
            {campaign.articles?.length ? (
              <Table striped highlightOnHover>
                <Table.Thead><Table.Tr><Table.Th>Date proposée</Table.Th><Table.Th>Article</Table.Th><Table.Th>Mot-clé principal</Table.Th><Table.Th>Statut</Table.Th><Table.Th>Résultat</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {campaign.articles.map((article) => (
                    <Table.Tr key={article.id}>
                      <Table.Td>{article.planned_for ? new Date(article.planned_for).toLocaleDateString("fr-FR") : "—"}</Table.Td>
                      <Table.Td>{article.title}</Table.Td>
                      <Table.Td>{article.primary_keyword}</Table.Td>
                      <Table.Td><Badge variant="light" color={article.status === "draft" ? "teal" : article.status === "failed" ? "red" : "gray"}>{article.status}</Badge></Table.Td>
                      <Table.Td>
                        {article.content_id ? <Text size="xs">Brouillon créé · {article.content_id.slice(0, 8)}</Text> : article.generation_error ? <Text size="xs" c="red">{article.generation_error}</Text> : <Text size="xs" c="dimmed">{article.generation_attempts ?? 0}/3 tentatives</Text>}
                        {article.published_url && <Text component="a" href={article.published_url} target="_blank" size="xs">Voir la publication</Text>}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            ) : <Text size="sm" c="dimmed">Aucun article dans cette campagne.</Text>}
          </Stack>
        </Card>
      ))}
    </Stack>
  );
}
