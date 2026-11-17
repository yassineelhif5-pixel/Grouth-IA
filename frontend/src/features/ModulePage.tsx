import { Button, Checkbox, Code, Group, JsonInput, Modal, NumberInput, Pagination, Select, Stack, Tabs, Textarea, TextInput } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { HistoryCentre } from "@/features/HistoryCentre";
import { useTenant } from "@/hooks/useMe";
import { api } from "@/services/api";
import type { Paged } from "@/types/api";
import { formatDate } from "@/utils/format";

export type Row = Record<string, unknown> & { id: string };
export interface Field {
  name: string;
  label: string;
  type?: "text" | "textarea" | "number" | "select" | "json" | "checkbox" | "tags";
  options?: (string | { value: string; label: string })[];
  required?: boolean;
}
export interface RowAction {
  label: string;
  path: (r: Row) => string;
  method?: "POST" | "GET";
  body?: (r: Row) => unknown;
  perm?: string;
  prompt?: string;
  show?: (r: Row) => boolean;
}

export const statusCol = (key = "status"): Column<Row> => ({ key, label: "Statut", render: (r) => <StatusBadge value={r[key] as string} /> });
export const dateCol = (key = "created_at", label = "Date"): Column<Row> => ({ key, label, render: (r) => formatDate(r[key] as string) });

function FieldInput({ f, value, onChange }: { f: Field; value: unknown; onChange: (v: unknown) => void }) {
  switch (f.type) {
    case "textarea":
      return <Textarea label={f.label} autosize minRows={3} value={(value as string) ?? ""} onChange={(e) => onChange(e.currentTarget.value)} />;
    case "number":
      return <NumberInput label={f.label} value={(value as number) ?? ""} onChange={(v) => onChange(v === "" ? null : v)} />;
    case "select":
      return <Select label={f.label} data={f.options ?? []} value={(value as string) ?? null} onChange={onChange} clearable />;
    case "checkbox":
      return <Checkbox label={f.label} checked={Boolean(value)} onChange={(e) => onChange(e.currentTarget.checked)} />;
    case "tags":
      return <TextInput label={`${f.label} (séparés par des virgules)`} value={Array.isArray(value) ? value.join(", ") : ""} onChange={(e) => onChange(e.currentTarget.value.split(",").map((s) => s.trim()).filter(Boolean))} />;
    case "json":
      return <JsonInput label={f.label} autosize minRows={4} formatOnBlur validationError="JSON invalide" value={typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2)} onChange={onChange} />;
    default:
      return <TextInput label={f.label} withAsterisk={f.required} value={(value as string) ?? ""} onChange={(e) => onChange(e.currentTarget.value)} />;
  }
}

function serialize(fields: Field[], v: Record<string, unknown>) {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const x = v[f.name];
    if (x === undefined || x === "") continue;
    out[f.name] = f.type === "json" && typeof x === "string" ? JSON.parse(x) : x;
  }
  return out;
}

/** Generic module page: list (pagination, filters via query), create form, row actions, history tab. Backed by the audited API. */
export function ModulePage({ title, endpoint, columns, fields = [], writePerm, actions = [], module, extra, defaultValues = {}, filters }: {
  title: string; endpoint: string; columns: Column<Row>[]; fields?: Field[]; writePerm?: string; actions?: RowAction[]; module: string;
  extra?: ReactNode; defaultValues?: Record<string, unknown>; filters?: Record<string, string>;
}) {
  const { t } = useTranslation();
  const { tenantId, can } = useTenant();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [opened, { open, close }] = useDisclosure(false);
  const [values, setValues] = useState<Record<string, unknown>>(defaultValues);
  const [result, setResult] = useState<unknown>(null);
  const key = [endpoint, tenantId, page, filters];
  const list = useQuery({ queryKey: key, queryFn: () => api<Paged<Row> | Row[]>(endpoint, { tenantId, query: { page, ...filters } }) });
  const rows = Array.isArray(list.data) ? list.data : list.data?.results;
  const create = useMutation({
    mutationFn: () => api<Row>(endpoint, { method: "POST", body: serialize(fields, values), tenantId }),
    onSuccess: () => { close(); setValues(defaultValues); notifications.show({ color: "green", message: "Enregistré" }); void qc.invalidateQueries({ queryKey: [endpoint] }); },
  });
  const act = useMutation({
    mutationFn: ({ a, r }: { a: RowAction; r: Row }) => {
      let body = a.body ? (a.body(r) as Record<string, unknown>) : {};
      if (a.prompt) {
        const answer = window.prompt(a.prompt);
        if (answer === null) throw new Error("Annulé");
        body = { ...body, reason: answer, value: answer };
      }
      return api<unknown>(a.path(r), { method: a.method ?? "POST", body: a.method === "GET" ? undefined : body, tenantId });
    },
    onSuccess: (res) => { setResult(res); notifications.show({ color: "green", message: "Action exécutée" }); void qc.invalidateQueries({ queryKey: [endpoint] }); },
  });
  const allowed = actions.filter((a) => !a.perm || can(a.perm));
  const cols: Column<Row>[] = allowed.length ? [...columns, { key: "_a", label: t("app.actions"), render: (r) => (
    <Group gap={4}>{allowed.filter((a) => !a.show || a.show(r)).map((a) => (
      <Button key={a.label} size="compact-xs" variant="light" loading={act.isPending} onClick={(e) => { e.stopPropagation(); act.mutate({ a, r }); }}>{a.label}</Button>))}
    </Group>) }] : columns;
  const hasMore = !Array.isArray(list.data) && Boolean(list.data?.next);
  return (
    <>
      <PageHeader title={title} actions={<Group>{extra}{fields.length > 0 && writePerm && can(writePerm) && <Button onClick={open}>{t("app.create")}</Button>}</Group>} />
      <Tabs defaultValue="list">
        <Tabs.List mb="sm"><Tabs.Tab value="list">Liste</Tabs.Tab><Tabs.Tab value="history">{t("nav.history")}</Tabs.Tab></Tabs.List>
        <Tabs.Panel value="list">
          <DataTable rows={rows} columns={cols} loading={list.isLoading} error={list.error} empty="Aucun élément" />
          {(hasMore || page > 1) && <Group justify="center" mt="md"><Pagination total={page + (hasMore ? 1 : 0)} value={page} onChange={setPage} /></Group>}
          {result !== null && <Code block mt="md">{JSON.stringify(result, null, 2)}</Code>}
        </Tabs.Panel>
        <Tabs.Panel value="history"><HistoryCentre scope="tenant" tenantId={tenantId} presetModule={module} /></Tabs.Panel>
      </Tabs>
      <Modal opened={opened} onClose={close} title={title} size="lg">
        <Stack>
          {fields.map((f) => <FieldInput key={f.name} f={f} value={values[f.name]} onChange={(v) => setValues({ ...values, [f.name]: v })} />)}
          <Group justify="flex-end"><Button variant="default" onClick={close}>{t("app.cancel")}</Button><Button loading={create.isPending} onClick={() => create.mutate()}>{t("app.save")}</Button></Group>
        </Stack>
      </Modal>
    </>
  );
}
