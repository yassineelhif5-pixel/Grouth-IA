import { Alert, Badge, Button, Card, Code, CopyButton, Group, Modal, NumberInput, Progress, Select, SimpleGrid, Stack, Table, Text, TextInput } from "@mantine/core";
import { IconCheck, IconCopy, IconUserPlus } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { useTenant } from "@/hooks/useMe";
import { api, ApiError } from "@/services/api";
import { formatDate } from "@/utils/format";

interface Member { id: string; user_id: string; display_name: string | null; email: string | null; username: string | null; status: string; joined_at: string | null; roles: string[]; license_code: string | null; license_name: string | null }
interface Allocation { code: string; name: string; description: string | null; modules: string[]; quantity: number; used: number; available: number }
interface Created { email: string; email_status: string; accept_path?: string }

export const ROLES = [
  { value: "tenant_admin", label: "Administrateur" }, { value: "tenant_manager", label: "Manager" }, { value: "marketing_manager", label: "Marketing" },
  { value: "seo_manager", label: "SEO" }, { value: "content_manager", label: "Contenus" }, { value: "social_media_manager", label: "Réseaux sociaux" },
  { value: "sales_manager", label: "Responsable commercial" }, { value: "sales_rep", label: "Commercial" }, { value: "analyst", label: "Analyste" },
  { value: "tenant_member", label: "Membre" }, { value: "tenant_viewer", label: "Lecture seule" },
];
const roleLabel = (c: string) => (c === "tenant_owner" ? "Propriétaire" : ROLES.find((r) => r.value === c)?.label ?? c);
const err = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

/** Shared by the tenant admin (own tenant) and the PILOTE (any tenant). */
export function UsersManager({ tenantId, pilot, canManage }: { tenantId: string; pilot: boolean; canManage: boolean }) {
  const qc = useQueryClient();
  const base = pilot ? `/pilot/tenants/${tenantId}` : "";
  const hdr = pilot ? {} : { tenantId };
  const members = useQuery({ queryKey: ["members", tenantId, pilot], queryFn: () => api<Member[]>(`${base}/members`, hdr) });
  const allocs = useQuery({ queryKey: ["licenses", tenantId, pilot], queryFn: () => api<Allocation[]>(`${base}/licenses`, hdr) });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["members", tenantId, pilot] }); void qc.invalidateQueries({ queryKey: ["licenses", tenantId, pilot] }); };
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => {
      if (pilot) return api(`${base}/members/${id}`, { method: "PUT", body });
      if ("license_code" in body) return api(`/members/${id}/license`, { method: "PUT", tenantId, body });
      return api(`/members/${id}`, { method: "PUT", tenantId, body });
    },
    onSuccess: refresh,
  });
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("tenant_member");
  const [lic, setLic] = useState<string | null>(null);
  const [created, setCreated] = useState<Created | null>(null);
  const create = useMutation({
    mutationFn: () => api<Created>(`${base}/members`, { ...hdr, method: "POST", body: { email, role_code: role, license_code: lic } }),
    onSuccess: (r) => { setCreated(r); refresh(); },
  });
  const licOptions = (allocs.data ?? []).map((a) => ({ value: a.code, label: `${a.name} (${a.available} dispo.)`, disabled: a.available <= 0 }));
  return (
    <Stack gap="lg">
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
        {(allocs.data ?? []).map((a) => (
          <Card key={a.code} padding="md">
            <Group justify="space-between"><Text fw={600}>{a.name}</Text><Text className="gi-num" size="sm">{a.used}/{a.quantity}</Text></Group>
            <Progress mt={8} value={a.quantity ? (100 * a.used) / a.quantity : 0} color={a.available === 0 && a.quantity > 0 ? "orange" : "signal"} radius="xl" />
            <Text size="xs" c="dimmed" mt={6} lineClamp={2}>{a.description ?? (a.modules.includes("*") ? "Tous les modules" : a.modules.join(", "))}</Text>
          </Card>
        ))}
      </SimpleGrid>
      {update.error && <Alert color="red">{err(update.error)}</Alert>}
      <Card>
        <Group justify="space-between" mb="md">
          <Text fw={600}>Utilisateurs ({members.data?.length ?? 0})</Text>
          {canManage && <Button leftSection={<IconUserPlus size={16} />} onClick={() => { setOpen(true); setCreated(null); setEmail(""); }}>Créer un utilisateur</Button>}
        </Group>
        <Table.ScrollContainer minWidth={820}>
          <Table>
            <Table.Thead><Table.Tr><Table.Th>Utilisateur</Table.Th><Table.Th>Rôle</Table.Th><Table.Th>Licence</Table.Th><Table.Th>Statut</Table.Th><Table.Th>Depuis</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {(members.data ?? []).map((m) => {
                const owner = m.roles.includes("tenant_owner");
                return (
                  <Table.Tr key={m.id}>
                    <Table.Td><Text size="sm" fw={500}>{m.display_name || m.username || m.email}</Text><Text size="xs" c="dimmed">{m.email}{m.username ? ` · @${m.username}` : ""}</Text></Table.Td>
                    <Table.Td>
                      {owner || !canManage ? <Badge variant="outline">{m.roles.map(roleLabel).join(", ") || "—"}</Badge> : (
                        <Select size="xs" w={190} data={ROLES} value={m.roles[0] ?? null} allowDeselect={false} aria-label="Rôle"
                          onChange={(v) => v && update.mutate({ id: m.id, body: { role_code: v, reason: "changement de rôle" } })} />
                      )}
                    </Table.Td>
                    <Table.Td>
                      {canManage ? (
                        <Select size="xs" w={210} clearable placeholder="Aucune licence" aria-label="Licence" value={m.license_code}
                          data={(allocs.data ?? []).map((a) => ({ value: a.code, label: `${a.name} (${a.available} dispo.)`, disabled: a.available <= 0 && a.code !== m.license_code }))}
                          onChange={(v) => update.mutate({ id: m.id, body: { license_code: v, reason: "attribution de licence" } })} />
                      ) : <Text size="sm">{m.license_name ?? "—"}</Text>}
                    </Table.Td>
                    <Table.Td>
                      {pilot && canManage && !owner ? (
                        <Select size="xs" w={130} data={[{ value: "active", label: "Actif" }, { value: "suspended", label: "Suspendu" }]} value={m.status} allowDeselect={false} aria-label="Statut"
                          onChange={(v) => v && update.mutate({ id: m.id, body: { status: v } })} />
                      ) : <Badge variant="dot" color={m.status === "active" ? "signal" : "gray"}>{m.status}</Badge>}
                    </Table.Td>
                    <Table.Td><Text size="xs" c="dimmed">{m.joined_at ? formatDate(m.joined_at) : "—"}</Text></Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Card>
      <Modal opened={open} onClose={() => setOpen(false)} title="Créer un utilisateur">
        {created ? (
          <Stack>
            <Alert color="signal" icon={<IconCheck size={16} />}>{created.email} est créé.</Alert>
            {created.email_status === "sent" ? <Text size="sm">Un e-mail d'invitation lui a été envoyé.</Text> : (
              <>
                <Text size="sm">Aucun e-mail n'a pu être envoyé ({created.email_status}). Transmettez-lui ce lien d'activation, affiché une seule fois :</Text>
                <Group gap="xs" wrap="nowrap"><Code block style={{ flex: 1, wordBreak: "break-all" }}>{`${window.location.origin}${created.accept_path ?? ""}`}</Code>
                  <CopyButton value={`${window.location.origin}${created.accept_path ?? ""}`}>{({ copied, copy }) => <Button size="xs" variant="light" onClick={copy} leftSection={copied ? <IconCheck size={14} /> : <IconCopy size={14} />}>{copied ? "Copié" : "Copier"}</Button>}</CopyButton></Group>
              </>
            )}
            <Button onClick={() => setOpen(false)}>Fermer</Button>
          </Stack>
        ) : (
          <Stack>
            <TextInput label="E-mail" type="email" required value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
            <Select label="Rôle" data={ROLES} value={role} allowDeselect={false} onChange={(v) => v && setRole(v)} />
            <Select label="Licence" placeholder="Attribuer plus tard" clearable data={licOptions} value={lic} onChange={setLic}
              description="Seules les licences encore disponibles pour ce tenant peuvent être attribuées." />
            {create.error && <Alert color="red">{err(create.error)}</Alert>}
            <Button loading={create.isPending} disabled={!/.+@.+\..+/.test(email)} onClick={() => create.mutate()}>Créer et inviter</Button>
          </Stack>
        )}
      </Modal>
    </Stack>
  );
}

export function UsersPage() {
  const { tenantId, can } = useTenant();
  return (
    <>
      <PageHeader title="Utilisateurs & licences" subtitle="Créez les comptes de votre équipe et attribuez les licences disponibles pour votre organisation." />
      <UsersManager tenantId={tenantId} pilot={false} canManage={can("members.manage")} />
    </>
  );
}

/** PILOTE: declare how many licences of each type a tenant gets. */
export function PilotLicenseAllocations({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["licenses", tenantId, true], queryFn: () => api<Allocation[]>(`/pilot/tenants/${tenantId}/licenses`) });
  const [draft, setDraft] = useState<Record<string, number>>({});
  useEffect(() => { if (q.data) setDraft(Object.fromEntries(q.data.map((a) => [a.code, a.quantity]))); }, [q.data]);
  const save = useMutation({
    mutationFn: () => api<Allocation[]>(`/pilot/tenants/${tenantId}/licenses`, { method: "PUT", body: { quantities: draft, reason: "PILOTE" } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["licenses", tenantId, true] }),
  });
  return (
    <Card>
      <Group justify="space-between" mb="sm"><Text fw={600}>Licences du tenant</Text><Button size="xs" loading={save.isPending} onClick={() => save.mutate()}>Enregistrer</Button></Group>
      {save.error && <Alert color="red" mb="sm">{err(save.error)}</Alert>}
      {save.isSuccess && <Alert color="signal" mb="sm">Licences enregistrées.</Alert>}
      <Table>
        <Table.Thead><Table.Tr><Table.Th>Type</Table.Th><Table.Th>Modules</Table.Th><Table.Th>Attribuées</Table.Th><Table.Th w={140}>Quantité</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>
          {(q.data ?? []).map((a) => (
            <Table.Tr key={a.code}>
              <Table.Td><Text size="sm" fw={500}>{a.name}</Text></Table.Td>
              <Table.Td><Text size="xs" c="dimmed">{a.modules.includes("*") ? "Tous" : a.modules.join(", ")}</Text></Table.Td>
              <Table.Td className="gi-num">{a.used}</Table.Td>
              <Table.Td><NumberInput size="xs" min={a.used} value={draft[a.code] ?? 0} onChange={(v) => setDraft((d) => ({ ...d, [a.code]: Number(v) || 0 }))} aria-label={`Quantité ${a.name}`} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  );
}
