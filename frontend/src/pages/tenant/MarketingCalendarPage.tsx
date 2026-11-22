import { Alert, Badge, Card, Group, Loader, Paper, Stack, Table, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";
import { useTenant } from "@/hooks/useMe";

type EditorialArticle = {
  id: string;
  title: string;
  primary_keyword: string;
  status: string;
  planned_for: string | null;
  published_url: string | null;
};
type Campaign = {
  id: string;
  name: string;
  status: string;
  timezone: string;
  generation_time: string;
  publish_requires_approval: boolean;
  starts_on: string | null;
  ends_on: string | null;
  article_count: number;
  articles: EditorialArticle[];
};

export function MarketingCalendarPage() {
  const { tenantId } = useTenant();
  const query = useQuery({
    queryKey: ["marketing-campaigns", tenantId],
    queryFn: () => api<Campaign[]>("/marketing/campaigns", { tenantId }),
  });
  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Calendrier éditorial</Title>
        <Text size="sm" c="dimmed">Les propositions validées deviennent un backlog éditorial. La génération et la publication automatiques ne sont pas encore activées.</Text>
      </div>
      <Alert color="blue" title="Contrôle de publication">
        Les campagnes créées restent en statut « planned ». La validation humaine des contenus reste obligatoire ; aucune publication n'est lancée par la création du calendrier.
      </Alert>
      {query.isLoading && <Loader />}
      {query.isError && <Alert color="red">{query.error instanceof Error ? query.error.message : "Erreur de chargement."}</Alert>}
      {!query.isLoading && !query.data?.length && <Paper withBorder p="lg"><Text c="dimmed">Aucune campagne pour le moment. Échangez avec l'assistant marketing, puis approuvez une stratégie pour préparer votre calendrier.</Text></Paper>}
      {query.data?.map((campaign) => (
        <Card key={campaign.id} withBorder radius="md">
          <Stack gap="sm">
            <Group justify="space-between">
              <Title order={4}>{campaign.name}</Title>
              <Badge color={campaign.status === "active" ? "green" : "gray"}>{campaign.status}</Badge>
            </Group>
            <Group gap="lg">
              <Text size="xs" c="dimmed">{campaign.article_count} articles</Text>
              <Text size="xs" c="dimmed">Génération prévue : {campaign.generation_time} ({campaign.timezone})</Text>
              <Text size="xs" c="dimmed">Approbation avant publication : {campaign.publish_requires_approval ? "oui" : "non"}</Text>
            </Group>
            {campaign.articles?.length ? (
              <Table striped highlightOnHover>
                <Table.Thead><Table.Tr><Table.Th>Date proposée</Table.Th><Table.Th>Article</Table.Th><Table.Th>Mot-clé principal</Table.Th><Table.Th>Statut</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>
                  {campaign.articles.map((article) => (
                    <Table.Tr key={article.id}>
                      <Table.Td>{article.planned_for ? new Date(article.planned_for).toLocaleDateString("fr-FR") : "—"}</Table.Td>
                      <Table.Td>{article.title}</Table.Td>
                      <Table.Td>{article.primary_keyword}</Table.Td>
                      <Table.Td><Badge variant="light" color="gray">{article.status}</Badge></Table.Td>
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
