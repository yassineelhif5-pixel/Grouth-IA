import { Badge, Button, Code, Drawer, Group, Pagination, Stack, Table, Tabs, Text, TextInput, Timeline } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DataTable } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/services/api";
import type { AuditEvent, EntityVersion, Paged } from "@/types/api";
import { diffObjects, formatDate, shortId } from "@/utils/format";

type Filters = Record<string, string>;
const FILTER_KEYS = ["from", "to", "user", "module", "action", "entity_type", "entity_id", "status", "product", "execution", "correlation_id"] as const;

/** History & audit centre. `scope` = tenant (X-Tenant-ID) or pilot (global, audited server-side). */
export function HistoryCentre({ scope, tenantId, canExport }: { scope: "tenant" | "pilot"; tenantId?: string; canExport?: boolean }) {
  const { t } = useTranslation();
  const prefix = scope === "pilot" ? "/pilot/history" : "/history";
  const [tab, setTab] = useState<string | null>("events");
  const [filters, setFilters] = useState<Filters>({});
  const [draft, setDraft] = useState<Filters>({});
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const [traceId, setTraceId] = useState<string | null>(null);
  const endpoint = tab === "events" ? `${prefix}/events` : tab === "activity" ? "/history/activity" : `${prefix}/executions`;
  const list = useQuery({
    queryKey: ["history", scope, tenantId, tab, filters, page],
    queryFn: () => api<Paged<Record<string, unknown> & { id: string }>>(endpoint, { tenantId, query: { ...filters, page, page_size: 50 } }),
  });
  const exportCsv = async () => {
    const res = await api<Response>("/history/export.csv", { tenantId, query: filters, raw: true });
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = "growth-history.csv";
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      <PageHeader title={t("history.title")} actions={canExport && scope === "tenant" && <Button variant="default" onClick={() => void exportCsv()}>{t("app.export")}</Button>} />
      <Group align="flex-end" mb="md" gap="xs" wrap="wrap">
        {FILTER_KEYS.map((k) => (
          <TextInput key={k} size="xs" w={k === "from" || k === "to" ? 190 : 150} type={k === "from" || k === "to" ? "datetime-local" : "text"}
            label={t(`history.${k === "from" || k === "to" ? "period" : k === "entity_type" || k === "entity_id" ? "entity" : k === "correlation_id" ? "correlation" : k}`) + (k === "from" ? " ≥" : k === "to" ? " <" : k === "entity_id" ? " id" : "")}
            value={draft[k] ?? ""} onChange={(e) => setDraft({ ...draft, [k]: e.currentTarget.value })} />
        ))}
        <Button size="xs" onClick={() => { setPage(1); setFilters(Object.fromEntries(Object.entries(draft).filter(([, v]) => v))); }}>{t("app.search")}</Button>
      </Group>
      <Tabs value={tab} onChange={(v) => { setTab(v); setPage(1); }}>
        <Tabs.List mb="sm">
          <Tabs.Tab value="events">{t("history.events")}</Tabs.Tab>
          {scope === "tenant" && <Tabs.Tab value="activity">{t("history.activity")}</Tabs.Tab>}
          <Tabs.Tab value="executions">{t("history.executions")}</Tabs.Tab>
        </Tabs.List>
      </Tabs>
      <DataTable rows={list.data?.results} loading={list.isLoading} error={list.error}
        onRowClick={tab === "events" ? (r) => setSelected(r as unknown as AuditEvent) : undefined}
        columns={tab === "executions" ? [
          { key: "created_at", label: t("history.date"), render: (r) => formatDate(r.created_at as string) },
          { key: "module", label: t("history.module") }, { key: "operation", label: "Operation" },
          { key: "status", label: t("history.status"), render: (r) => <StatusBadge value={r.status as string} /> },
          { key: "duration_ms", label: "ms" }, { key: "error_message", label: "Erreur" },
          { key: "correlation_id", label: t("history.correlation"), render: (r) => <Code onClick={(e) => { e.stopPropagation(); setTraceId(r.correlation_id as string); }} style={{ cursor: "pointer" }}>{shortId(r.correlation_id as string)}</Code> },
        ] : [
          { key: "created_at", label: t("history.date"), render: (r) => formatDate(r.created_at as string) },
          { key: "actor", label: t("history.actor"), render: (r) => `${(r.actor_type as string) ?? ""} ${shortId((r.actor_user_id ?? r.user_id) as string)}` },
          { key: "action", label: t("history.action"), render: (r) => (r.action ?? r.event_type) as string },
          { key: "module", label: t("history.module") },
          { key: "entity", label: t("history.entity"), render: (r) => `${(r.entity_type as string) ?? "—"} ${shortId(r.entity_id as string)}` },
          { key: "status", label: t("history.status"), render: (r) => r.status ? <StatusBadge value={r.status as string} /> : null },
        ]} />
      <Group justify="center" mt="md">
        <Pagination total={page + (list.data?.has_more ? 1 : 0)} value={page} onChange={setPage} />
      </Group>
      <EventDrawer event={selected} onClose={() => setSelected(null)} tenantId={tenantId} scope={scope} onTrace={setTraceId} />
      <TraceDrawer correlationId={traceId} onClose={() => setTraceId(null)} tenantId={tenantId} scope={scope} />
    </>
  );
}

function EventDrawer({ event, onClose, tenantId, scope, onTrace }: { event: AuditEvent | null; onClose: () => void; tenantId?: string; scope: string; onTrace: (c: string) => void }) {
  const { t } = useTranslation();
  const versions = useQuery({
    queryKey: ["versions", event?.entity_type, event?.entity_id],
    enabled: !!event?.entity_type && !!event.entity_id && scope === "tenant",
    retry: false,
    queryFn: () => api<EntityVersion[]>(`/history/entities/${event!.entity_type}/${event!.entity_id}/versions`, { tenantId }),
  });
  if (!event) return null;
  const diff = diffObjects(event.before_data, event.after_data);
  const hidden = event.before_data === null && event.after_data === null;
  return (
    <Drawer opened={!!event} onClose={onClose} position="right" size="lg" title={event.action}>
      <Stack>
        <Table>
          <Table.Tbody>
            {([["history.date", formatDate(event.created_at)], ["history.actor", `${event.actor_type} ${event.actor_user_id ?? ""}`],
              ["history.entity", `${event.entity_type ?? "—"} ${event.entity_id ?? ""}`], ["history.source", event.source],
              ["history.status", event.status], ["app.requestId", event.request_id ?? "—"]] as const).map(([k, v]) => (
              <Table.Tr key={k}><Table.Th w={160}>{t(k)}</Table.Th><Table.Td>{v}</Table.Td></Table.Tr>
            ))}
            <Table.Tr><Table.Th>{t("history.correlation")}</Table.Th><Table.Td>
              <Group gap="xs"><Code>{event.correlation_id}</Code>{event.correlation_id && <Button size="compact-xs" variant="light" onClick={() => onTrace(event.correlation_id!)}>{t("history.trace")}</Button>}</Group>
            </Table.Td></Table.Tr>
          </Table.Tbody>
        </Table>
        {event.description && <Text size="sm">{event.description}</Text>}
        {hidden ? <Text c="dimmed" size="sm">{t("history.noValues")}</Text> : (
          <Table striped>
            <Table.Thead><Table.Tr><Table.Th>Champ</Table.Th><Table.Th>{t("history.before")}</Table.Th><Table.Th>{t("history.after")}</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>{diff.map((d) => (
              <Table.Tr key={d.field}><Table.Td>{d.field}</Table.Td><Table.Td><Code>{JSON.stringify(d.before)}</Code></Table.Td><Table.Td><Code>{JSON.stringify(d.after)}</Code></Table.Td></Table.Tr>
            ))}</Table.Tbody>
          </Table>
        )}
        {versions.data && versions.data.length > 0 && (
          <>
            <Text fw={600}>{t("history.versions")}</Text>
            <Timeline active={0} bulletSize={18}>
              {versions.data.map((v) => (
                <Timeline.Item key={v.id} title={<Group gap={6}><Badge size="sm">v{v.version_number}</Badge><Text size="sm">{v.operation}</Text></Group>}>
                  <Text size="xs" c="dimmed">{formatDate(v.created_at)} · {v.changed_fields?.join(", ") ?? ""}</Text>
                  {v.change_reason && <Text size="xs">{v.change_reason}</Text>}
                </Timeline.Item>
              ))}
            </Timeline>
          </>
        )}
      </Stack>
    </Drawer>
  );
}

interface Trace { audit_events: Record<string, string>[]; activity_events: Record<string, string>[]; entity_history: Record<string, string>[]; executions: Record<string, string>[] }

function TraceDrawer({ correlationId, onClose, tenantId, scope }: { correlationId: string | null; onClose: () => void; tenantId?: string; scope: string }) {
  const q = useQuery({
    queryKey: ["trace", correlationId], enabled: !!correlationId,
    queryFn: () => api<Trace>(`${scope === "pilot" ? "/pilot/history" : "/history"}/trace/${correlationId}`, { tenantId }),
  });
  const items = q.data ? [
    ...q.data.audit_events.map((e) => ({ at: e.created_at ?? "", kind: "audit", label: `${e.action} (${e.status})` })),
    ...q.data.entity_history.map((e) => ({ at: e.created_at ?? "", kind: "history", label: `${e.entity_type} v${e.version_number} ${e.operation}` })),
    ...q.data.executions.map((e) => ({ at: e.created_at ?? "", kind: "execution", label: `${e.module}:${e.operation} ${e.status} ${e.duration_ms ?? ""}ms` })),
    ...q.data.activity_events.map((e) => ({ at: e.created_at ?? "", kind: "activity", label: e.event_type ?? "" })),
  ].sort((a, b) => a.at.localeCompare(b.at)) : [];
  return (
    <Drawer opened={!!correlationId} onClose={onClose} position="right" size="md" title={`Trace ${shortId(correlationId)}`}>
      <Timeline bulletSize={14}>
        {items.map((i, n) => (
          <Timeline.Item key={n} title={<Group gap={6}><Badge size="xs" variant="outline">{i.kind}</Badge><Text size="sm">{i.label}</Text></Group>}>
            <Text size="xs" c="dimmed">{formatDate(i.at)}</Text>
          </Timeline.Item>
        ))}
      </Timeline>
    </Drawer>
  );
}
