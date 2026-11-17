import { describe, expect, it, vi } from "vitest";

vi.mock("./supabase", () => ({ supabase: { auth: { getSession: async () => ({ data: { session: { access_token: "jwt" } } }) } } }));

import { api, ApiError, buildUrl } from "./api";

describe("api client", () => {
  it("builds query strings without empty values", () => {
    expect(buildUrl("/history/events", { module: "products", user: "", page: 2 })).toBe("/api/v1/history/events?module=products&page=2");
  });

  it("sends JWT, tenant and correlation headers and maps errors", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: { code: "quota_exceeded", message: "Quota", request_id: "r1" } }), { status: 402 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api("/schedulers", { method: "POST", body: {}, tenantId: "t1", correlationId: "c1" })).rejects.toBeInstanceOf(ApiError);
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const h = init.headers as Record<string, string>;
    expect(h.Authorization).toBe("Bearer jwt");
    expect(h["X-Tenant-ID"]).toBe("t1");
    expect(h["X-Correlation-ID"]).toBe("c1");
  });
});
