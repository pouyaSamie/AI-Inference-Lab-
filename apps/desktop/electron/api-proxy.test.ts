import { describe, expect, it, vi } from "vitest";
import { ApiProxy } from "./api-proxy";
import type { SettingsStore } from "./settings";

function settings(token: string | null = "operator-token"): SettingsStore {
  return {
    baseUrl: "http://127.0.0.1:8787",
    getToken: () => token,
  } as unknown as SettingsStore;
}

describe("validated API proxy", () => {
  it("attaches the bearer token only in the main process request", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const proxy = new ApiProxy(settings(), fetchMock as unknown as typeof fetch);
    const result = await proxy.request("GET", "/api/v1/status", undefined, null);

    expect(result).toMatchObject({ status: 200, ok: true, body: { status: "ok" } });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(String(url)).toBe("http://127.0.0.1:8787/api/v1/status");
    expect(init.redirect).toBe("error");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer operator-token");
  });

  it("rejects paths outside the operator API before calling fetch", async () => {
    const fetchMock = vi.fn();
    const proxy = new ApiProxy(settings(), fetchMock as unknown as typeof fetch);
    for (const path of ["/health", "/api/v1/../secret", "http://evil.example/api/v1/status", "/api/v1/%2e%2e/x"]) {
      const result = await proxy.request("GET", path, undefined, null);
      expect(result.ok).toBe(false);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects oversized bodies and unsupported methods", async () => {
    const fetchMock = vi.fn();
    const proxy = new ApiProxy(settings(), fetchMock as unknown as typeof fetch);
    expect((await proxy.request("DELETE", "/api/v1/status", undefined, null)).ok).toBe(false);
    expect(
      (await proxy.request("POST", "/api/v1/recipes", { padding: "x".repeat(1_100_000) }, null)).ok,
    ).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces controller errors without inventing a success", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const proxy = new ApiProxy(settings(null), fetchMock as unknown as typeof fetch);
    const result = await proxy.request("GET", "/api/v1/status", undefined, null);
    expect(result).toMatchObject({ status: 401, ok: false, body: { detail: "unauthorized" } });
    const [, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("turns transport failures into a typed proxy failure", async () => {
    const fetchMock = vi.fn(async () => {
      throw new Error("connect ECONNREFUSED 127.0.0.1:8787");
    });
    const proxy = new ApiProxy(settings(), fetchMock as unknown as typeof fetch);
    const result = await proxy.request("GET", "/api/v1/status", undefined, null);
    expect(result).toMatchObject({
      status: 0,
      ok: false,
      body: null,
      error: "connect ECONNREFUSED 127.0.0.1:8787",
    });
  });
});
