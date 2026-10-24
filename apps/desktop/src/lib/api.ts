import type {
  BenchmarkObservation,
  ComparisonCreateRequest,
  ComparisonEvidenceRequest,
  ComparisonListResponse,
  ComparisonPlan,
  ContextEvaluation,
  ExperimentListResponse,
  ExperimentPlan,
  ExperimentResultsResponse,
  ExperimentStatusView,
  ExperimentView,
  JobEvent,
  PlanRequest,
  PlanResponse,
  RecipeListResponse,
  RecipeView,
  ReleaseCheckRequest,
  ReleaseCheckResponse,
  ReleaseDetailResponse,
  ReleaseListResponse,
  Schemas,
  SystemStatusResponse,
  WorkerListResponse,
  WorkerSnapshot,
} from "./contracts";
import type { BridgeEvent, BridgeResponse, BridgeSettingsStatus } from "./bridge";
import { createMockApi, type MockApi } from "./mock";
import { consumeSseBuffer, dispatchSseMessage } from "./sse";

export class ApiError extends Error {
  readonly status: number;
  readonly details: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export type EventHandler = (event: string, id: number | null, data: unknown) => void;

export interface LabApi {
  readonly demo: boolean;
  status(): Promise<SystemStatusResponse>;
  workers(): Promise<WorkerListResponse>;
  workerSnapshot(workerId: string): Promise<WorkerSnapshot>;
  workerCommands(workerId: string): Promise<Schemas["CommandStatusView"][]>;
  experiments(limit?: number): Promise<ExperimentListResponse>;
  experiment(experimentId: string): Promise<ExperimentView>;
  eventPage(experimentId: string, after?: number, limit?: number): Promise<Schemas["EventPage"]>;
  plan(request: PlanRequest): Promise<PlanResponse>;
  createExperiment(plan: ExperimentPlan): Promise<ExperimentView>;
  pause(experimentId: string): Promise<ExperimentView>;
  resume(experimentId: string): Promise<ExperimentView>;
  cancel(experimentId: string, reason: string): Promise<ExperimentView>;
  retryPreflight(experimentId: string): Promise<ExperimentView>;
  results(experimentId: string): Promise<ExperimentResultsResponse>;
  recipes(experimentId?: string): Promise<RecipeListResponse>;
  runRecipe(recipeId: string): Promise<Schemas["CommandStatusView"]>;
  serving(workerId: string): Promise<Schemas["ServingSession"] | null>;
  stopRecipe(workerId: string, sessionId: string): Promise<Schemas["CommandStatusView"]>;
  recipeChat(workerId: string, body: Schemas["RecipeChatRequest"]): Promise<Schemas["CommandStatusView"]>;
  recipe(recipeId: string): Promise<RecipeView>;
  createRecipe(experimentId: string, candidateId: string): Promise<RecipeView>;
  verifyRecipe(recipeId: string): Promise<Record<string, unknown>>;
  promoteRecipe(
    recipeId: string,
    body: { target_slot: string; dry_run: boolean },
  ): Promise<Record<string, unknown>>;
  releases(): Promise<ReleaseListResponse>;
  release(noticeId: string): Promise<ReleaseDetailResponse>;
  checkRelease(body: ReleaseCheckRequest): Promise<ReleaseCheckResponse>;
  decideRelease(
    noticeId: string,
    body: { action: "pin" | "defer"; note?: string },
  ): Promise<ReleaseDetailResponse>;
  comparisons(noticeId?: string): Promise<ComparisonListResponse>;
  createComparison(body: ComparisonCreateRequest): Promise<ComparisonPlan>;
  submitComparisonEvidence(
    comparisonId: string,
    body: ComparisonEvidenceRequest,
  ): Promise<ComparisonPlan>;
  subscribeEvents(experimentId: string, lastEventId: number, handler: EventHandler): () => void;
  saveReport(suggestedName: string, content: string): Promise<{ canceled: boolean; path?: string }>;
  settingsStatus(): Promise<BridgeSettingsStatus>;
  setApiBaseUrl(url: string): Promise<BridgeSettingsStatus>;
  setToken(token: string): Promise<BridgeSettingsStatus>;
  clearToken(): Promise<BridgeSettingsStatus>;
  appInfo(): Promise<{ version: string; platform: string; packaged: boolean; security?: Record<string, unknown> }>;
}

interface LiveTransport {
  request<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
    idempotencyKey?: string | null,
  ): Promise<BridgeResponse<T>>;
  subscribe(experimentId: string, lastEventId: number, handler: EventHandler): () => void;
  saveReport(suggestedName: string, content: string): Promise<{ canceled: boolean; path?: string }>;
  settingsStatus(): Promise<BridgeSettingsStatus>;
  setApiBaseUrl(url: string): Promise<BridgeSettingsStatus>;
  setToken(token: string): Promise<BridgeSettingsStatus>;
  clearToken(): Promise<BridgeSettingsStatus>;
  appInfo(): Promise<{ version: string; platform: string; packaged: boolean; security?: Record<string, unknown> }>;
}

const BROWSER_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? window.location.origin;

function browserTransport(): LiveTransport {
  const request = async <T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
    idempotencyKey?: string | null,
  ): Promise<BridgeResponse<T>> => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
    const response = await fetch(new URL(path, BROWSER_BASE), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(20_000),
    });
    const text = await response.text();
    let parsed: unknown = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = { message: text.slice(0, 2_000) };
    }
    return { status: response.status, ok: response.ok, body: parsed as T };
  };

  const subscribe = (experimentId: string, lastEventId: number, handler: EventHandler): (() => void) => {
    let stopped = false;
    let controller: AbortController | null = null;
    let last = lastEventId;
    let attempt = 0;

    const run = async (): Promise<void> => {
      while (!stopped) {
        controller = new AbortController();
        try {
          const headers: Record<string, string> = { Accept: "text/event-stream" };
                const url = new URL(
            `/api/v1/experiments/${encodeURIComponent(experimentId)}/events`,
            BROWSER_BASE,
          );
          url.searchParams.set("last_event_id", String(last));
          const response = await fetch(url, {
            headers,
            signal: controller.signal,
            cache: "no-store",
          });
          if (!response.ok || !response.body) throw new Error(`event stream HTTP ${response.status}`);
          attempt = 0;
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          while (!stopped) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parsed = consumeSseBuffer(buffer);
            buffer = parsed.rest;
            for (const message of parsed.messages) {
              if (message.id !== null) last = Math.max(last, message.id);
              if (message.event === "snapshot") attempt = 0;
              dispatchSseMessage(message, handler);
            }
          }
        } catch (error) {
          if (stopped || controller.signal.aborted) return;
          handler("transport.error", null, {
            message: error instanceof Error ? error.message : "event stream disconnected",
            retry_in_ms: Math.min(15_000, 500 * 2 ** attempt),
          });
        }
        if (stopped) return;
        attempt += 1;
        await new Promise((resolve) => setTimeout(resolve, Math.min(15_000, 500 * 2 ** attempt)));
      }
    };

    void run();
    return () => {
      stopped = true;
      controller?.abort();
    };
  };

  return {
    request,
    subscribe,
    async saveReport(suggestedName, content) {
      const blob = new Blob([content], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = suggestedName.endsWith(".json") ? suggestedName : `${suggestedName}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      return { canceled: false, path: anchor.download };
    },
    async settingsStatus() {
      return {
        api_base_url: BROWSER_BASE,
        token_configured: false,
        persistent: false,
        storage_backend: "browser session",
        secure_storage_available: false,
        note: "Browser mode has no secure token bridge and cannot authenticate. Use the packaged desktop app.",
      };
    },
    async setApiBaseUrl() {
      throw new ApiError("The backend URL can only be changed in the packaged desktop app.", 400);
    },
    async setToken() {
      throw new ApiError("Browser mode has no secure token storage. Use the packaged desktop app.", 400);
    },
    async clearToken() {
      throw new ApiError("Browser mode has no secure token storage. Use the packaged desktop app.", 400);
    },
    async appInfo() {
      return { version: "browser", platform: navigator.platform, packaged: false };
    },
  };
}

function desktopTransport(bridge: NonNullable<Window["labDesktop"]>): LiveTransport {
  return {
    async request<T>(
      method: "GET" | "POST",
      path: string,
      body?: unknown,
      idempotencyKey?: string | null,
    ) {
      return bridge.api.request<T>(method, path, body, idempotencyKey ?? null);
    },
    subscribe(experimentId, lastEventId, handler) {
      let subscriptionId: string | null = null;
      let stopped = false;
      const off = bridge.api.onEvent((message: BridgeEvent) => {
        if (subscriptionId === null || message.subscription_id !== subscriptionId) return;
        handler(message.event, message.id, message.data);
      });
      void bridge.api
        .subscribeEvents(experimentId, lastEventId)
        .then((id) => {
          if (stopped) void bridge.api.unsubscribeEvents(id);
          else subscriptionId = id;
        })
        .catch((error: unknown) => {
          handler("transport.error", null, {
            message: error instanceof Error ? error.message : "event subscription failed",
            retry_in_ms: 2_000,
          });
        });
      return () => {
        stopped = true;
        off();
        if (subscriptionId) void bridge.api.unsubscribeEvents(subscriptionId);
      };
    },
    saveReport: (suggestedName, content) => bridge.saveReport(suggestedName, content),
    settingsStatus: () => bridge.settings.status(),
    setApiBaseUrl: (url) => bridge.settings.setApiBaseUrl(url),
    setToken: (token) => bridge.settings.setToken(token),
    clearToken: () => bridge.settings.clearToken(),
    appInfo: () => bridge.appInfo(),
  };
}

class HttpClient implements LabApi {
  runRecipe(recipeId: string) {
    return this.json<Schemas["CommandStatusView"]>("POST", `/api/v1/recipes/${encodeURIComponent(recipeId)}/run`, undefined, crypto.randomUUID());
  }
  serving(workerId: string) {
    return this.json<Schemas["ServingSession"] | null>("GET", `/api/v1/serving/${encodeURIComponent(workerId)}`);
  }
  stopRecipe(workerId: string, sessionId: string) {
    return this.json<Schemas["CommandStatusView"]>("POST", `/api/v1/serving/${encodeURIComponent(workerId)}/${encodeURIComponent(sessionId)}/stop`);
  }
  recipeChat(workerId: string, body: Schemas["RecipeChatRequest"]) {
    return this.json<Schemas["CommandStatusView"]>("POST", `/api/v1/serving/${encodeURIComponent(workerId)}/chat`, body, crypto.randomUUID());
  }
  readonly demo = false;
  private readonly transport: LiveTransport;

  constructor(transport: LiveTransport) {
    this.transport = transport;
  }

  private async json<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
    idempotencyKey?: string | null,
  ): Promise<T> {
    const response = await this.transport.request<T>(method, path, body, idempotencyKey);
    if (!response.ok) {
      const detail = response.body as { detail?: unknown; message?: unknown } | null;
      const message =
        response.error ??
        (typeof detail?.message === "string" ? detail.message : null) ??
        (typeof detail?.detail === "string" ? detail.detail : null) ??
        `Controller request failed with HTTP ${response.status}`;
      throw new ApiError(message, response.status, response.body);
    }
    return response.body;
  }

  status() {
    return this.json<SystemStatusResponse>("GET", "/api/v1/status");
  }
  workers() {
    return this.json<WorkerListResponse>("GET", "/api/v1/workers");
  }
  workerSnapshot(workerId: string) {
    return this.json<WorkerSnapshot>(
      "GET",
      `/api/v1/workers/${encodeURIComponent(workerId)}/snapshot`,
    );
  }
  workerCommands(workerId: string) { return this.json<Schemas["CommandStatusView"][]>("GET", `/api/v1/workers/${encodeURIComponent(workerId)}/commands`); }
  experiments(limit = 50) {
    return this.json<ExperimentListResponse>("GET", `/api/v1/experiments?limit=${limit}`);
  }
  experiment(experimentId: string) {
    return this.json<ExperimentView>(
      "GET",
      `/api/v1/experiments/${encodeURIComponent(experimentId)}`,
    );
  }
  eventPage(experimentId: string, after = 0, limit = 100) {
    return this.json<Schemas["EventPage"]>(
      "GET",
      `/api/v1/experiments/${encodeURIComponent(experimentId)}/events/page?after=${after}&limit=${limit}`,
    );
  }
  plan(request: PlanRequest) {
    return this.json<PlanResponse>("POST", "/api/v1/experiments/plan", request);
  }
  createExperiment(plan: ExperimentPlan) {
    return this.json<ExperimentView>(
      "POST",
      "/api/v1/experiments",
      { plan },
      crypto.randomUUID(),
    );
  }
  pause(experimentId: string) {
    return this.json<ExperimentView>(
      "POST",
      `/api/v1/experiments/${encodeURIComponent(experimentId)}/pause`,
    );
  }
  resume(experimentId: string) {
    return this.json<ExperimentView>(
      "POST",
      `/api/v1/experiments/${encodeURIComponent(experimentId)}/resume`,
    );
  }
  cancel(experimentId: string, reason: string) {
    const query = new URLSearchParams({ reason });
    return this.json<ExperimentView>(
      "POST",
      `/api/v1/experiments/${encodeURIComponent(experimentId)}/cancel?${query.toString()}`,
    );
  }
  retryPreflight(experimentId: string) {
    return this.json<ExperimentView>(
      "POST",
      `/api/v1/experiments/${encodeURIComponent(experimentId)}/preflight/retry`,
    );
  }
  results(experimentId: string) {
    return this.json<ExperimentResultsResponse>(
      "GET",
      `/api/v1/experiments/${encodeURIComponent(experimentId)}/results`,
    );
  }
  recipes(experimentId?: string) {
    const query = experimentId ? `?experiment_id=${encodeURIComponent(experimentId)}` : "";
    return this.json<RecipeListResponse>("GET", `/api/v1/recipes${query}`);
  }
  recipe(recipeId: string) {
    return this.json<RecipeView>("GET", `/api/v1/recipes/${encodeURIComponent(recipeId)}`);
  }
  createRecipe(experimentId: string, candidateId: string) {
    return this.json<RecipeView>(
      "POST",
      "/api/v1/recipes",
      { experiment_id: experimentId, candidate_id: candidateId },
      crypto.randomUUID(),
    );
  }
  verifyRecipe(recipeId: string) {
    return this.json<Record<string, unknown>>(
      "POST",
      `/api/v1/recipes/${encodeURIComponent(recipeId)}/verify`,
    );
  }
  promoteRecipe(recipeId: string, body: { target_slot: string; dry_run: boolean }) {
    return this.json<Record<string, unknown>>(
      "POST",
      `/api/v1/recipes/${encodeURIComponent(recipeId)}/promote`,
      body,
    );
  }
  releases() {
    return this.json<ReleaseListResponse>("GET", "/api/v1/releases");
  }
  release(noticeId: string) {
    return this.json<ReleaseDetailResponse>(
      "GET",
      `/api/v1/releases/${encodeURIComponent(noticeId)}`,
    );
  }
  checkRelease(body: ReleaseCheckRequest) {
    return this.json<ReleaseCheckResponse>("POST", "/api/v1/releases/check", body);
  }
  decideRelease(noticeId: string, body: { action: "pin" | "defer"; note?: string }) {
    return this.json<ReleaseDetailResponse>(
      "POST",
      `/api/v1/releases/${encodeURIComponent(noticeId)}/decision`,
      body,
    );
  }
  comparisons(noticeId?: string) {
    const query = noticeId ? `?notice_id=${encodeURIComponent(noticeId)}` : "";
    return this.json<ComparisonListResponse>("GET", `/api/v1/comparisons${query}`);
  }
  createComparison(body: ComparisonCreateRequest) {
    return this.json<ComparisonPlan>("POST", "/api/v1/comparisons", body);
  }
  submitComparisonEvidence(comparisonId: string, body: ComparisonEvidenceRequest) {
    return this.json<ComparisonPlan>(
      "POST",
      `/api/v1/comparisons/${encodeURIComponent(comparisonId)}/evidence`,
      body,
    );
  }
  subscribeEvents(experimentId: string, lastEventId: number, handler: EventHandler) {
    return this.transport.subscribe(experimentId, lastEventId, handler);
  }
  saveReport(suggestedName: string, content: string) {
    return this.transport.saveReport(suggestedName, content);
  }
  settingsStatus() {
    return this.transport.settingsStatus();
  }
  setApiBaseUrl(url: string) {
    return this.transport.setApiBaseUrl(url);
  }
  setToken(token: string) {
    return this.transport.setToken(token);
  }
  clearToken() {
    return this.transport.clearToken();
  }
  appInfo() {
    return this.transport.appInfo();
  }
}

class DemoClient implements LabApi {
  async runRecipe(_recipeId: string): Promise<Schemas["CommandStatusView"]> {
    throw new ApiError("Demo mode cannot launch an engine.", 409);
  }
  async serving(_workerId: string): Promise<Schemas["ServingSession"] | null> { return null; }
  async stopRecipe(_workerId: string, _sessionId: string): Promise<Schemas["CommandStatusView"]> {
    throw new ApiError("Demo mode has no running engine.", 409);
  }
  async recipeChat(_workerId: string, _body: Schemas["RecipeChatRequest"]): Promise<Schemas["CommandStatusView"]> {
    throw new ApiError("Demo mode cannot send model requests.", 409);
  }
  readonly demo = true;
  private readonly mock: MockApi;

  constructor(mock: MockApi) {
    this.mock = mock;
  }

  status() {
    return this.mock.status();
  }
  workers() {
    return this.mock.workers();
  }
  workerSnapshot(workerId: string) {
    return this.mock.workerSnapshot(workerId);
  }
  async workerCommands(_workerId: string): Promise<Schemas["CommandStatusView"][]> { return []; }
  experiments() {
    return this.mock.experiments();
  }
  experiment(experimentId: string) {
    return this.mock.experiment(experimentId);
  }
  async eventPage(experimentId: string, _after = 0, _limit = 100) {
    const view = await this.mock.experiment(experimentId);
    return {
      events: [],
      last_event_id: view.status.last_event_id ?? 0,
      replay_floor: 1,
      has_more: false,
    };
  }
  plan(request: PlanRequest) {
    return this.mock.plan(request) as Promise<PlanResponse>;
  }
  async createExperiment(_plan: ExperimentPlan): Promise<ExperimentView> {
    throw new ApiError("Demo mode cannot create experiment evidence.", 409);
  }
  pause(experimentId: string) {
    return this.mock.pause(experimentId);
  }
  resume(experimentId: string) {
    return this.mock.resume(experimentId);
  }
  cancel(experimentId: string, _reason: string) {
    return this.mock.cancel(experimentId);
  }
  retryPreflight(experimentId: string) {
    return this.mock.retryPreflight(experimentId);
  }
  results(experimentId: string) {
    return this.mock.results(experimentId);
  }
  recipes(experimentId?: string) {
    return this.mock.recipes().then((response) => ({
      ...response,
      recipes: experimentId
        ? response.recipes.filter((item) => item.experiment_id === experimentId)
        : response.recipes,
      total: experimentId
        ? response.recipes.filter((item) => item.experiment_id === experimentId).length
        : response.total,
    }));
  }
  recipe(recipeId: string) {
    return this.mock.recipe(recipeId);
  }
  createRecipe(experimentId: string, candidateId: string) {
    return this.mock.createRecipe(experimentId, candidateId);
  }
  verifyRecipe(recipeId: string) {
    return this.mock.verifyRecipe(recipeId);
  }
  promoteRecipe(recipeId: string, body: { target_slot: string; dry_run: boolean }) {
    return this.mock.promoteRecipe(recipeId, body);
  }
  releases() {
    return this.mock.releases();
  }
  release(noticeId: string) {
    return this.mock.release(noticeId);
  }
  checkRelease(body: ReleaseCheckRequest) {
    return this.mock.checkRelease(body);
  }
  decideRelease(noticeId: string, body: { action: "pin" | "defer"; note?: string }) {
    return this.mock.decideRelease(noticeId, body);
  }
  comparisons(noticeId?: string) {
    return this.mock.comparisons(noticeId);
  }
  createComparison(body: ComparisonCreateRequest) {
    return this.mock.createComparison(body);
  }
  submitComparisonEvidence(comparisonId: string, body: ComparisonEvidenceRequest) {
    return this.mock.submitComparisonEvidence(comparisonId, body);
  }
  subscribeEvents(experimentId: string, lastEventId: number, handler: EventHandler) {
    return this.mock.subscribeEvents(experimentId, lastEventId, handler);
  }
  saveReport(suggestedName: string, _content: string) {
    return this.mock.saveReport().then((result) => ({ ...result, path: result.path ?? suggestedName }));
  }
  async settingsStatus(): Promise<BridgeSettingsStatus> {
    return {
      api_base_url: "demo://offline-fixtures",
      token_configured: false,
      persistent: false,
      storage_backend: "none (offline demo)",
      secure_storage_available: false,
      note: "Offline demo data is active. No controller, worker or engine was contacted.",
    };
  }
  setApiBaseUrl(_url: string) {
    return this.settingsStatus();
  }
  setToken(_token: string) {
    return this.settingsStatus();
  }
  clearToken() {
    return this.settingsStatus();
  }
  async appInfo() {
    return { version: "demo", platform: "desktop", packaged: false };
  }
}

export function demoRequested(): boolean {
  const params = new URLSearchParams(window.location.search);
  return params.get("demo") === "1" || window.localStorage.getItem("lab.demo") === "1";
}

export function setDemoRequested(enabled: boolean): void {
  if (enabled) {
    window.localStorage.setItem("lab.demo", "1");
    return;
  }
  window.localStorage.removeItem("lab.demo");
  // `?demo=1` is an explicit launch override. Turning demo off must clear it or
  // createLabApi() would immediately re-enter demo mode.
  const url = new URL(window.location.href);
  if (url.searchParams.has("demo")) {
    url.searchParams.delete("demo");
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }
}

export function createLabApi(): LabApi {
  if (demoRequested()) return new DemoClient(createMockApi(new URLSearchParams(window.location.search).get("demoScenario") ?? "default"));
  if (window.labDesktop) return new HttpClient(desktopTransport(window.labDesktop));
  return new HttpClient(browserTransport());
}

export function isContextEvaluation(value: unknown): value is ContextEvaluation {
  return typeof value === "object" && value !== null && "candidate_id" in value;
}

export function isObservation(value: unknown): value is BenchmarkObservation {
  return typeof value === "object" && value !== null && "observation_id" in value;
}

export type { ExperimentStatusView, JobEvent };
