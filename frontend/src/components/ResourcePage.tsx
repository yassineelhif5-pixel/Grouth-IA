import { Button, Group, Modal, Stack, TextInput, Textarea } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { useTenant } from "@/hooks/useMe";
import { api } from "@/services/api";
import type { Paged } from "@/types/api";

export interface FieldDef {
  name: string;
  label: string;
  multiline?: boolean;
  required?: boolean;
}

/** Generic tenant-scoped CRUD page (list + create + soft delete), backed by the audited Django API. */
export function ResourcePage<T extends { id: string }>({ title, endpoint, columns, fields, writePerm }: {
  title: string;
  endpoint: string;
  columns: Column<T>[];
  fields: FieldDef[];
  writePerm: string;
}) {
  const { t } = useTranslation();
  const { tenantId, can } = useTenant();
  const qc = useQueryClient();
  const [opened, { open, close }] = useDisclosure(false);
  const schema = z.object(Object.fromEntries(fields.map((f) => [f.name, f.required ? z.string().min(1) : z.string().optional()])));
  const form = useForm<Record<string, string>>({ resolver: zodResolver(schema) as never });
  const key = [endpoint, tenantId];
  const list = useQuery({ queryKey: key, queryFn: () => api<Paged<T>>(endpoint, { tenantId }) });
  const create = useMutation({
    mutationFn: (body: Record<string, string>) => api<T>(endpoint, { method: "POST", body, tenantId }),
    onSuccess: () => { close(); form.reset(); void qc.invalidateQueries({ queryKey: key }); },
  });
  const remove = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => api(`${endpoint}/${id}`, { method: "DELETE", query: { reason }, tenantId }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: key }),
  });
  const cols: Column<T>[] = [
    ...columns,
    ...(can(writePerm)
      ? [{ key: "_actions", label: t("app.actions"), render: (r: T) => (
          <Button size="xs" variant="subtle" color="red" onClick={(e) => {
            e.stopPropagation();
            const reason = window.prompt(t("app.reason"));
            if (reason) remove.mutate({ id: r.id, reason });
          }}>{t("app.delete")}</Button>) }]
      : []),
  ];
  return (
    <>
      <PageHeader title={title} actions={can(writePerm) && <Button onClick={open}>{t("app.create")}</Button>} />
      <DataTable rows={list.data?.results} columns={cols} loading={list.isLoading} error={list.error} />
      <Modal opened={opened} onClose={close} title={title}>
        <form onSubmit={form.handleSubmit((v) => create.mutate(v))}>
          <Stack>
            {fields.map((f) => f.multiline
              ? <Textarea key={f.name} label={f.label} {...form.register(f.name)} error={form.formState.errors[f.name]?.message as string | undefined} />
              : <TextInput key={f.name} label={f.label} withAsterisk={f.required} {...form.register(f.name)} error={form.formState.errors[f.name]?.message as string | undefined} />)}
            <Group justify="flex-end">
              <Button variant="default" onClick={close}>{t("app.cancel")}</Button>
              <Button type="submit" loading={create.isPending}>{t("app.save")}</Button>
            </Group>
          </Stack>
        </form>
      </Modal>
    </>
  );
}
