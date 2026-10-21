import { describe, expect, it } from "vitest";
import {
  isTrustedFrameUrl,
  validateApiBaseUrl,
  validateApiPath,
  validateExperimentId,
  validateIdempotencyKey,
  validateLastEventId,
  validateMethod,
  validateReportContent,
  validateReportName,
} from "./security";

describe("desktop IPC security validation", () => {
  it("allows only loopback http and any https origin", () => {
    expect(validateApiBaseUrl("http://127.0.0.1:8000")).toMatchObject({
      ok: true,
      value: "http://127.0.0.1:8000",
    });
    expect(validateApiBaseUrl("http://localhost:8000/")).toMatchObject({
      ok: true,
      value: "http://localhost:8000",
    });
    expect(validateApiBaseUrl("http://10.0.0.4:8000").ok).toBe(false);
    expect(validateApiBaseUrl("https://controller.example.com").ok).toBe(true);
    expect(validateApiBaseUrl("ftp://127.0.0.1:8000").ok).toBe(false);
    expect(validateApiBaseUrl("http://user:pass@127.0.0.1:8000").ok).toBe(false);
    expect(validateApiBaseUrl("https://controller.example.com/api").ok).toBe(false);
  });

  it("allows only /api/v1 JSON routes and rejects traversal", () => {
    expect(validateApiPath("/api/v1/status")).toMatchObject({ ok: true });
    expect(validateApiPath("/api/v1/experiments?limit=5")).toMatchObject({ ok: true });
    expect(validateApiPath("/health").ok).toBe(false);
    expect(validateApiPath("/api/v1/../secrets").ok).toBe(false);
    expect(validateApiPath("/api/v1/%2e%2e/secrets").ok).toBe(false);
    expect(validateApiPath("/api/v1/experiments\\..\\x").ok).toBe(false);
    expect(validateApiPath("http://evil/api/v1/status").ok).toBe(false);
  });

  it("validates methods, experiment IDs, event IDs and idempotency keys", () => {
    expect(validateMethod("GET").ok).toBe(true);
    expect(validateMethod("POST").ok).toBe(true);
    expect(validateMethod("DELETE").ok).toBe(false);
    expect(validateExperimentId("exp-123").ok).toBe(true);
    expect(validateExperimentId("../exp").ok).toBe(false);
    expect(validateLastEventId(-1).ok).toBe(false);
    expect(validateLastEventId("12")).toMatchObject({ ok: true, value: 12 });
    expect(validateIdempotencyKey("6f1a0b0e-6c37-4e5c-9a0e-123456789abc").ok).toBe(true);
    expect(validateIdempotencyKey("bad key").ok).toBe(false);
  });

  it("keeps report writes to bounded basenames", () => {
    expect(validateReportName("results.json")).toMatchObject({ ok: true, value: "results.json" });
    expect(validateReportName("../../escape.json").ok).toBe(false);
    expect(validateReportName("/etc/passwd").ok).toBe(false);
    expect(validateReportName("script.sh").ok).toBe(true);
    expect(validateReportName("binary.exe").ok).toBe(false);
    expect(validateReportContent("{}").ok).toBe(true);
    expect(validateReportContent(123).ok).toBe(false);
  });

  it("trusts only the app scheme or the loopback dev origin", () => {
    expect(isTrustedFrameUrl("lab://app/index.html")).toBe(true);
    expect(isTrustedFrameUrl("http://127.0.0.1:5173/", "http://127.0.0.1:5173")).toBe(true);
    expect(isTrustedFrameUrl("http://localhost:5173/", "http://localhost:5173")).toBe(true);
    expect(isTrustedFrameUrl("https://evil.example/", "http://127.0.0.1:5173")).toBe(false);
    expect(isTrustedFrameUrl("http://127.0.0.1:5174/", "http://127.0.0.1:5173")).toBe(false);
    expect(isTrustedFrameUrl("https://127.0.0.1:5173/", "http://127.0.0.1:5173")).toBe(false);
    expect(isTrustedFrameUrl("file:///tmp/index.html")).toBe(false);
    expect(isTrustedFrameUrl("not-a-url")).toBe(false);
  });
});
