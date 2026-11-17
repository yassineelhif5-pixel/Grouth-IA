import { Alert, Center, Loader, ScrollArea, Table, Text } from "@mantine/core";
import type { ReactNode } from "react";

import { ApiError } from "@/services/api";

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
}

export function DataTable<T extends { id?: string }>({ rows, columns, loading, error, onRowClick, empty = "—" }: {
  rows: T[] | undefined;
  columns: Column<T>[];
  loading?: boolean;
  error?: unknown;
  onRowClick?: (row: T) => void;
  empty?: string;
}) {
  if (loading) return <Center p="xl"><Loader /></Center>;
  if (error) {
    const e = error as ApiError;
    return <Alert color="red" title={e.code ?? "error"}>{e.message}{e.requestId ? ` (ref ${e.requestId.slice(0, 8)})` : ""}</Alert>;
  }
  if (!rows?.length) return <Text c="dimmed" p="md">{empty}</Text>;
  return (
    <ScrollArea>
      <Table striped highlightOnHover verticalSpacing="xs">
        <Table.Thead>
          <Table.Tr>{columns.map((c) => <Table.Th key={c.key}>{c.label}</Table.Th>)}</Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r, i) => (
            <Table.Tr key={r.id ?? i} onClick={onRowClick ? () => onRowClick(r) : undefined} style={{ cursor: onRowClick ? "pointer" : undefined }}>
              {columns.map((c) => (
                <Table.Td key={c.key}>{c.render ? c.render(r) : String((r as Record<string, unknown>)[c.key] ?? "—")}</Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  );
}
