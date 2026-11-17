export function formatDate(value: string | null | undefined, locale = "fr"): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString(locale === "en" ? "en-GB" : "fr-FR", { dateStyle: "short", timeStyle: "medium" });
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "—";
}

/** Field-level diff between two JSON snapshots (used by the history centre). */
export function diffObjects(before: Record<string, unknown> | null | undefined, after: Record<string, unknown> | null | undefined) {
  const keys = Array.from(new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])).sort();
  return keys
    .filter((k) => JSON.stringify(before?.[k]) !== JSON.stringify(after?.[k]))
    .map((k) => ({ field: k, before: before?.[k], after: after?.[k] }));
}

export function toCsvSafe(value: unknown): string {
  const s = value === null || value === undefined ? "" : String(value);
  return /^[=+\-@]/.test(s) ? `'${s}` : s;
}
