import { describe, expect, it, vi } from "vitest";

import { ApiClient } from "@/api/client";
import { clearAccessToken, getAccessToken, setAccessToken } from "@/api/session";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("ApiClient 鉴权与 POST", () => {
  it("有令牌时注入 Authorization: Bearer", async () => {
    setAccessToken("tok-123");
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    const client = new ApiClient({ fetchImpl });

    await client.getJson("/v1/auth/me");

    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/auth/me", {
      headers: { Accept: "application/json", Authorization: "Bearer tok-123" },
    });
    clearAccessToken();
  });

  it("无令牌时不带 Authorization（保持既有行为）", async () => {
    clearAccessToken();
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    const client = new ApiClient({ fetchImpl });

    await client.getJson("/v1/live");

    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/live", {
      headers: { Accept: "application/json" },
    });
    expect(getAccessToken()).toBeNull();
  });

  it("postJson 使用 POST、JSON body 与 content-type", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ access_token: "t" }));
    const client = new ApiClient({ fetchImpl });

    const body = await client.postJson("/v1/auth/login", { email: "a", password: "b" });

    expect(body).toEqual({ access_token: "t" });
    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: "a", password: "b" }),
      headers: { Accept: "application/json", "content-type": "application/json" },
    });
  });
});
