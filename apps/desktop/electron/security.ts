export const API_PREFIX = "/api/v1/";
export const MAX_BODY_BYTES = 1_048_576;
export const MAX_REPORT_BYTES = 4_194_304;

const LOOPBACK = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);
const CONTROL = /[\u0000-\u001f\u007f]/;
const PATH_ENCODING = /%(2e|2f|5c)/i;

export interface Validation<T> {
  ok: boolean;
  value?: T;
  reason?: string;
}

export function validateApiBaseUrl(raw: unknown): Validation<string> {
  if (typeof raw !== "string") return { ok: false, reason: "API URL must be a string" };
  const value = raw.trim();
  if (!value || value.length > 2048) return { ok: false, reason: "API URL is empty or too long" };
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return { ok: false, reason: "API URL is not a valid URL" };
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return { ok: false, reason: "API URL must use http or https" };
  }
  if (url.username || url.password) {
    return { ok: false, reason: "API URL must not embed credentials" };
  }
  if (url.hash || url.search) {
    return { ok: false, reason: "API URL must not contain a query or fragment" };
  }
  if (url.pathname !== "/" && url.pathname !== "") {
    return { ok: false, reason: "API URL must not contain a path" };
  }
  if (url.protocol === "http:" && !LOOPBACK.has(url.hostname.toLowerCase())) {
    return { ok: false, reason: "Plain HTTP is allowed only for loopback hosts; use HTTPS for a remote controller" };
  }
  if (CONTROL.test(value)) return { ok: false, reason: "API URL contains control characters" };
  return { ok: true, value: `${url.origin}` };
}

export function validateApiPath(raw: unknown): Validation<string> {
  if (typeof raw !== "string") return { ok: false, reason: "API path must be a string" };
  if (raw.length === 0 || raw.length > 2048) return { ok: false, reason: "API path is empty or too long" };
  if (!raw.startsWith(API_PREFIX)) return { ok: false, reason: "Only /api/v1 routes are allowed" };
  if (raw.includes("\\") || raw.includes("..") || CONTROL.test(raw)) {
    return { ok: false, reason: "API path contains forbidden characters" };
  }
  if (PATH_ENCODING.test(raw.split("?")[0] ?? "")) {
    return { ok: false, reason: "API path contains encoded traversal characters" };
  }
  let parsed: URL;
  try {
    parsed = new URL(raw, "http://127.0.0.1");
  } catch {
    return { ok: false, reason: "API path is malformed" };
  }
  if (!parsed.pathname.startsWith(API_PREFIX)) {
    return { ok: false, reason: "Only /api/v1 routes are allowed" };
  }
  if (parsed.hash) return { ok: false, reason: "API path must not contain a fragment" };
  return { ok: true, value: `${parsed.pathname}${parsed.search}` };
}

export function validateMethod(raw: unknown): Validation<"GET" | "POST"> {
  if (raw === "GET" || raw === "POST") return { ok: true, value: raw };
  return { ok: false, reason: "Only GET and POST are supported" };
}

export function validateIdempotencyKey(raw: unknown): Validation<string | null> {
  if (raw === undefined || raw === null || raw === "") return { ok: true, value: null };
  if (typeof raw !== "string" || raw.length > 128 || !/^[A-Za-z0-9._:-]+$/.test(raw)) {
    return { ok: false, reason: "Idempotency-Key is invalid" };
  }
  return { ok: true, value: raw };
}

export function validateExperimentId(raw: unknown): Validation<string> {
  if (typeof raw !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(raw)) {
    return { ok: false, reason: "Experiment ID is invalid" };
  }
  return { ok: true, value: raw };
}

export function validateSubscriptionId(raw: unknown): Validation<string> {
  if (typeof raw !== "string" || !/^[A-Za-z0-9-]{8,128}$/.test(raw)) {
    return { ok: false, reason: "Subscription ID is invalid" };
  }
  return { ok: true, value: raw };
}

export function validateLastEventId(raw: unknown): Validation<number> {
  const value = typeof raw === "number" ? raw : Number(raw ?? 0);
  if (!Number.isSafeInteger(value) || value < 0 || value > 9_007_199_254_740_991) {
    return { ok: false, reason: "Last-Event-ID must be a non-negative integer" };
  }
  return { ok: true, value };
}

export function validateReportName(raw: unknown): Validation<string> {
  const fallback = "experiment-report.json";
  if (raw === undefined || raw === null || raw === "") return { ok: true, value: fallback };
  if (typeof raw !== "string" || raw.length > 160) return { ok: false, reason: "Report filename is invalid" };
  if (raw.includes("/") || raw.includes("\\") || raw.includes("..") || CONTROL.test(raw)) {
    return { ok: false, reason: "Report filename must be a plain basename" };
  }
  if (!/\.(json|ya?ml|sh|service|txt)$/i.test(raw)) {
    return { ok: false, reason: "Report filename must end in .json, .yaml, .yml, .sh, .service or .txt" };
  }
  return { ok: true, value: raw };
}

export function validateReportContent(raw: unknown): Validation<string> {
  if (typeof raw !== "string") return { ok: false, reason: "Report content must be text" };
  if (Buffer.byteLength(raw, "utf8") > MAX_REPORT_BYTES) {
    return { ok: false, reason: "Report content is too large" };
  }
  return { ok: true, value: raw };
}

export function isTrustedFrameUrl(raw: string, devOrigin?: string | null): boolean {
  try {
    const url = new URL(raw);
    if (url.protocol === "lab:" && url.host === "app") return true;
    if (devOrigin) {
      const dev = new URL(devOrigin);
      const loopbackDev = dev.protocol === "http:" && ["127.0.0.1", "localhost"].includes(dev.hostname);
      return loopbackDev && url.origin === dev.origin;
    }
    return false;
  } catch {
    return false;
  }
}

export function sanitizeMessage(value: unknown): string {
  const raw = value instanceof Error ? value.message : String(value ?? "request failed");
  return raw.replace(/[\r\n\t]+/g, " ").slice(0, 400);
}

export const IPC = {
  updatesStatus: "lab:engines:updates-status",
  updatesCheck: "lab:engines:updates-check",
  updatesPreference: "lab:engines:updates-preference",
  updatesInstall: "lab:engines:updates-install",
  engineRemove: "lab:engines:remove",
  runtimeStatus: "lab:runtime:status",
  runtimeReset: "lab:runtime:reset-data",
  runtimeRetry: "lab:runtime:retry",
  runtimeSelect: "lab:runtime:select",
  runtimeUseEngine: "lab:runtime:use-engine",
  runtimeRemoveFolder: "lab:runtime:remove-folder",
  appInfo: "lab:app:info",
  settingsStatus: "lab:settings:status",
  settingsSetUrl: "lab:settings:set-url",
  settingsSetToken: "lab:settings:set-token",
  settingsClearToken: "lab:settings:clear-token",
  apiRequest: "lab:api:request",
  eventsSubscribe: "lab:events:subscribe",
  eventsUnsubscribe: "lab:events:unsubscribe",
  eventsEvent: "lab:events:event",
  saveReport: "lab:save-report",
} as const;
