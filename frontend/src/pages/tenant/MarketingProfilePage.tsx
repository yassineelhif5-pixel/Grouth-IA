import { Alert, Button, Card, Group, Stack, Text, TextInput, Textarea, Title } from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { useTenant } from "@/hooks/useMe";

type Profile = {
  company_name?: string | null;
  industry?: string | null;
  offer?: string | null;
  target_audience?: string | null;
  differentiators?: string | null;
  objectives?: string[];
  preferred_language?: string;
  website_url?: string | null;
  timezone?: string;
};

export function MarketingProfilePage() {
  const { tenantId } = useTenant();
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["marketing-profile", tenantId],
    queryFn: () => api<Profile>("/marketing/profile", { tenantId }),
  });
  const [form, setForm] = useState<Profile>({ preferred_language: "fr", timezone: "Europe/Paris", objectives: [] });
  useEffect(() => {
    if (query.data) setForm({ ...query.data });
  }, [query.data]);
  const save = useMutation({
    mutationFn: () => api<Profile>("/marketing/profile", { method: "PUT", tenantId, body: form }),
    onSuccess: (profile) => {
      setForm(profile);
      qc.invalidateQueries({ queryKey: ["marketing-profile", tenantId] });
    },
  });
  const set = (key: keyof Profile, value: string) => setForm((old) => ({ ...old, [key]: value }));
  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Profil marketing du tenant</Title>
        <Text size="sm" c="dimmed">Ces informations aident l'assistant à comprendre votre activité. Elles sont fournies par vous, pas extraites automatiquement de votre site.</Text>
      </div>
      <Alert color="blue" title="Aucune analyse automatique du site">
        L'adresse du site est facultative et sert uniquement de référence contextuelle. Growth AI ne lance aucun crawler ou audit depuis ce profil.
      </Alert>
      {query.isError && <Alert color="red">{query.error instanceof Error ? query.error.message : "Impossible de charger le profil."}</Alert>}
      <Card withBorder radius="md">
        <Stack gap="md">
          <TextInput label="Nom de l'entreprise" value={form.company_name ?? ""} onChange={(e) => set("company_name", e.currentTarget.value)} />
          <TextInput label="Secteur d'activité" value={form.industry ?? ""} onChange={(e) => set("industry", e.currentTarget.value)} />
          <Textarea label="Offres, produits ou services" minRows={3} value={form.offer ?? ""} onChange={(e) => set("offer", e.currentTarget.value)} />
          <Textarea label="Public cible" minRows={2} value={form.target_audience ?? ""} onChange={(e) => set("target_audience", e.currentTarget.value)} />
          <Textarea label="Différenciation et avantages" minRows={2} value={form.differentiators ?? ""} onChange={(e) => set("differentiators", e.currentTarget.value)} />
          <Textarea label="Objectifs marketing (un par ligne)" minRows={3}
            value={(form.objectives ?? []).join("\n")}
            onChange={(e) => setForm((old) => ({ ...old, objectives: e.currentTarget.value.split("\n").map((x) => x.trim()).filter(Boolean) }))} />
          <TextInput label="Site web (facultatif)" placeholder="https://exemple.fr" value={form.website_url ?? ""} onChange={(e) => set("website_url", e.currentTarget.value)} />
          <TextInput label="Fuseau horaire" value={form.timezone ?? "Europe/Paris"} onChange={(e) => set("timezone", e.currentTarget.value)} />
          <Group justify="flex-end">
            <Button onClick={() => save.mutate()} loading={save.isPending}>Enregistrer le profil</Button>
          </Group>
          {save.isError && <Alert color="red">{save.error instanceof Error ? save.error.message : "Erreur d'enregistrement."}</Alert>}
          {save.isSuccess && <Alert color="green">Profil marketing enregistré.</Alert>}
        </Stack>
      </Card>
    </Stack>
  );
}
