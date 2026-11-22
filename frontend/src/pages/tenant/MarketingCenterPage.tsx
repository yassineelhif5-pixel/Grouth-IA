import { Badge, Button, Card, Group, SimpleGrid, Stack, Text, ThemeIcon, Title } from "@mantine/core";
import {
  IconCalendarTime,
  IconChecklist,
  IconPlugConnected,
  IconPencil,
  IconChecklist,
  IconReportAnalytics,
  IconSearch,
  IconShare,
  IconSparkles,
  IconVideo,
  IconWorldSearch,
} from "@tabler/icons-react";
import { Link, useParams } from "react-router-dom";

type MarketingArea = {
  title: string;
  description: string;
  path: string;
  icon: typeof IconSparkles;
  status: string;
};

const areas: MarketingArea[] = [
  {
    title: "Profil marketing",
    description: "Renseigner votre activité, vos offres, votre public cible et vos objectifs pour guider les échanges avec l'assistant.",
    path: "/marketing/profile",
    icon: IconChecklist,
    status: "Configuration tenant",
  },
  {
    title: "Calendrier éditorial",
    description: "Consulter les campagnes préparées et les articles proposés après validation de la stratégie.",
    path: "/marketing/calendar",
    icon: IconCalendarTime,
    status: "Planification",
  },
  {
    title: "Assistant & stratégie IA",
    description: "Préparer votre stratégie marketing à partir de vos échanges avec l'assistant et définir vos priorités éditoriales.",
    path: "/marketing/assistant",
    icon: IconSparkles,
    status: "Assistant dédié",
  },
  {
    title: "SEO & mots-clés",
    description: "Accéder aux outils SEO existants pour organiser les audits, les sujets et les optimisations de visibilité.",
    path: "/seo",
    icon: IconSearch,
    status: "Module existant",
  },
  {
    title: "GEO & visibilité IA",
    description: "Suivre les fonctionnalités de visibilité dans les moteurs et assistants de recherche générative.",
    path: "/geo",
    icon: IconWorldSearch,
    status: "Module existant",
  },
  {
    title: "Content Studio",
    description: "Créer, améliorer, versionner et préparer les articles et autres contenus pour validation.",
    path: "/content",
    icon: IconPencil,
    status: "Module existant",
  },
  {
    title: "Réseaux sociaux",
    description: "Gérer les comptes connectés et les publications sociales autorisées par les plateformes.",
    path: "/social",
    icon: IconShare,
    status: "Module existant",
  },
  {
    title: "Calendrier & Scheduler",
    description: "Consulter les programmations et automatisations déjà disponibles pour votre tenant.",
    path: "/scheduler",
    icon: IconCalendarTime,
    status: "Module existant",
  },
  {
    title: "Centre de validation",
    description: "Retrouver les demandes de validation avant les actions de publication.",
    path: "/approvals",
    icon: IconChecklist,
    status: "Module existant",
  },
  {
    title: "Connecteurs",
    description: "Configurer et vérifier les intégrations disponibles pour vos canaux de publication.",
    path: "/connectors",
    icon: IconPlugConnected,
    status: "Module existant",
  },
  {
    title: "YouTube & vidéo",
    description: "Accéder aux outils vidéo existants. La connexion d'une chaîne et les autorisations de publication restent distinctes.",
    path: "/video",
    icon: IconVideo,
    status: "Module vidéo existant",
  },
  {
    title: "Analytics & reporting",
    description: "Consulter les rapports et indicateurs réellement collectés par Growth AI.",
    path: "/reporting",
    icon: IconReportAnalytics,
    status: "Module existant",
  },
];

export function MarketingCenterPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const base = `/t/${tenantId ?? ""}`;

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Group justify="space-between" align="center">
          <div>
            <Title order={2}>Tenant Marketing Center</Title>
            <Text c="dimmed" size="sm">
              Votre espace central pour piloter la stratégie, les contenus et les publications marketing.
            </Text>
          </div>
          <Badge color="teal" variant="light">Espace tenant</Badge>
        </Group>
      </Stack>

      <Card withBorder radius="md" padding="md">
        <Group align="flex-start" gap="sm">
          <ThemeIcon size="lg" radius="md" variant="light" color="teal">
            <IconSparkles size={20} />
          </ThemeIcon>
          <Stack gap={3} style={{ flex: 1 }}>
            <Text fw={600}>Une stratégie pilotée par vos besoins</Text>
            <Text size="sm" c="dimmed">
              Décrivez vos objectifs à l'assistant. Growth AI pourra vous aider à construire une proposition éditoriale,
              que vous pourrez examiner et valider avant d'activer une campagne. L'analyse automatique de votre site
              web n'est pas utilisée pour établir cette stratégie.
            </Text>
          </Stack>
        </Group>
      </Card>

      <SimpleGrid cols={{ base: 1, sm: 2, xl: 3 }} spacing="md">
        {areas.map((area) => {
          const Icon = area.icon;
          return (
            <Card key={area.path} withBorder radius="md" padding="lg">
              <Stack gap="sm" h="100%">
                <Group justify="space-between" align="flex-start">
                  <ThemeIcon size={42} radius="md" variant="light">
                    <Icon size={22} />
                  </ThemeIcon>
                  <Badge variant="outline" color="gray">{area.status}</Badge>
                </Group>
                <Text fw={600}>{area.title}</Text>
                <Text size="sm" c="dimmed" style={{ flex: 1 }}>{area.description}</Text>
                <Button component={Link} to={`${base}${area.path}`} variant="light" fullWidth>
                  Ouvrir
                </Button>
              </Stack>
            </Card>
          );
        })}
      </SimpleGrid>
    </Stack>
  );
}
