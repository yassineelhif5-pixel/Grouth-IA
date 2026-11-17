import { supabase } from "./supabase";

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown>; request_id?: string };
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId?: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
  }
}

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api/v1";

export const newCorrelationId = (): string => crypto.randomUUID();

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  tenantId?: string | null;
  query?: Record<string, string | number | boolean | undefined | null>;
  correlationId?: string;
  raw?: boolean;
}

export function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const qs = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  });
  const s = qs.toString();
  return `${BASE}${path}${s ? `?${s}` : ""}`;
}

/** Every call carries the Supabase JWT, the selected tenant (verified server-side) and a correlation id. */
export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Correlation-ID": opts.correlationId ?? newCorrelationId(),
    "Accept-Language": document.documentElement.lang || "fr",
  };
  if (data.session) headers.Authorization = `Bearer ${data.session.access_token}`;
  if (opts.tenantId) headers["X-Tenant-ID"] = opts.tenantId;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(buildUrl(path, opts.query), {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  const json = (await res.json().catch(() => ({}))) as unknown;
  if (!res.ok) {
    const e = (json as Partial<ApiErrorBody>).error;
    throw new ApiError(res.status, e?.code ?? "error", e?.message ?? res.statusText, e?.request_id, e?.details);
  }
  return json as T;
}
