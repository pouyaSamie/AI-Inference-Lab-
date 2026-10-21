import {
  MAX_BODY_BYTES,
  sanitizeMessage,
  validateApiPath,
  validateIdempotencyKey,
  validateMethod,
} from "./security";
import type { SettingsStore } from "./settings";

export interface ProxyResponse {
  status: number;
  ok: boolean;
  body: unknown;
  error?: string;
}

const MAX_RESPONSE_BYTES = 8 * 1_048_576;

export class ApiProxy {
  private readonly settings: SettingsStore;
  private readonly fetchImpl: typeof fetch;

  constructor(settings: SettingsStore, fetchImpl: typeof fetch = globalThis.fetch) {
    this.settings = settings;
    this.fetchImpl = fetchImpl;
  }

  async request(
    methodRaw: unknown,
    pathRaw: unknown,
    body: unknown,
    idempotencyRaw: unknown,
  ): Promise<ProxyResponse> {
    const method = validateMethod(methodRaw);
    if (!method.ok) return failure(method.reason ?? "Unsupported method");
    const path = validateApiPath(pathRaw);
    if (!path.ok || !path.value) return failure(path.reason ?? "Invalid API path");
    const idempotency = validateIdempotencyKey(idempotencyRaw);
    if (!idempotency.ok) return failure(idempotency.reason ?? "Invalid idempotency key");

    let serialized: string | undefined;
    if (body !== undefined && body !== null) {
      try {
        serialized = JSON.stringify(body);
      } catch {
        return failure("Request body is not serializable");
      }
      if (serialized === undefined) return failure("Request body is not serializable");
      if (Buffer.byteLength(serialized, "utf8") > MAX_BODY_BYTES) {
        return failure("Request body is too large");
      }
    }

    const headers: Record<string, string> = { Accept: "application/json" };
    if (serialized !== undefined) headers["Content-Type"] = "application/json";
    const token = this.settings.getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (idempotency.value) headers["Idempotency-Key"] = idempotency.value;

    try {
      const url = new URL(path.value, this.settings.baseUrl);
      const response = await this.fetchImpl(url, {
        method: method.value,
        headers,
        body: serialized,
        redirect: "error",
        cache: "no-store",
        signal: AbortSignal.timeout(30_000),
      });
      const declared = Number(response.headers.get("content-length") ?? "0");
      if (Number.isFinite(declared) && declared > MAX_RESPONSE_BYTES) {
        return { status: response.status, ok: false, body: null, error: "Controller response is too large" };
      }
      const text = await response.text();
      if (Buffer.byteLength(text, "utf8") > MAX_RESPONSE_BYTES) {
        return { status: response.status, ok: false, body: null, error: "Controller response is too large" };
      }
      let parsed: unknown = null;
      if (text) {
        try {
          parsed = JSON.parse(text) as unknown;
        } catch {
          parsed = { message: text.slice(0, 2_000) };
        }
      }
      return { status: response.status, ok: response.ok, body: parsed };
    } catch (error) {
      const message = sanitizeMessage(error);
      return {
        status: 0,
        ok: false,
        body: null,
        error: message.toLowerCase().includes("abort") ? "Controller request timed out" : message,
      };
    }
  }
}

function failure(reason: string): ProxyResponse {
  return { status: 0, ok: false, body: null, error: reason };
}
