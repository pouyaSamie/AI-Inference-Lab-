export interface BridgeResponse<T> {
  status: number;
  ok: boolean;
  body: T;
  error?: string;
}

export interface BridgeEvent {
  subscription_id: string;
  event: string;
  id: number | null;
  data: unknown;
}

export interface BridgeSettingsStatus {
  api_base_url: string;
  token_configured: boolean;
  persistent: boolean;
  storage_backend: string;
  secure_storage_available: boolean;
  note: string;
}

export type RuntimePathKind = "model_roots" | "engine_roots" | "llama_server_path" | "llama_bench_path" | "llama_lib_dir" | "strata_path" | "strata_server_script" | "strata_python";
export interface DiscoveredEngineBuild {
  id: string;
  engine_id: "llamacpp" | "strata";
  label: string;
  paths: Partial<Record<Exclude<RuntimePathKind, "model_roots" | "engine_roots">, string>>;
  missing: string[];
  recommended?: boolean;
  version?: string | null;
  build_number?: number | null;
  version_source?: string | null;
}
export interface VerificationProgress { updated_at?: number; state: string; model_id?: string | null; bytes_done: number; bytes_total: number; files_done: number; files_total: number; current_file?: string; current_path?: string }
export interface LocalRuntimeStatus {
  managed: true;
  state: "stopped" | "starting" | "ready" | "needs_configuration" | "error";
  message: string;
  config: { model_roots: string[]; engine_roots?: string[] } & Partial<Record<Exclude<RuntimePathKind, "model_roots" | "engine_roots">, string>>;
  secure_storage: boolean;
  inventory?: { verification?: VerificationProgress; models: number; engines: number; gpus: number; verified_models: number; warnings: string[] };
  engine_candidates?: DiscoveredEngineBuild[];
}

export interface EngineReleaseOffer {
  engine_id: "llamacpp" | "strata"; version: string; tag: string; published: string;
  preview: boolean; installed_version: string | null; update: "available" | "current" | "unknown";
  assets: { id: number; name: string; size: number; digest: string; download_size?: number }[];
  recommendation?: { asset_id: number | null; label: string; reason: string; hardware: string };
  support?: { size: number }; page: string;
}
export interface EngineUpdateStatus {
  enabled: boolean; checking: boolean; checked_at: string | null; error: string | null;
  releases: EngineReleaseOffer[]; operation: string | null;
  installation?: { engine_id: "llamacpp" | "strata"; asset_id: number; version: string; phase: "downloading" | "unpacking" | "complete" | "failed"; bytes_done: number; bytes_total: number };
  hardware?: { architecture: string; gpus: { name: string }[]; warnings: string[] };
}
export interface DesktopBridge {
  engineUpdates?: {
    status(): Promise<EngineUpdateStatus | null>;
    check(): Promise<EngineUpdateStatus>;
    setEnabled(enabled: boolean): Promise<EngineUpdateStatus>;
    install(family: string, assetId: number): Promise<{ canceled: boolean }>;
    remove(buildId: string): Promise<{ canceled: boolean }>;
  };
  runtime?: {
    resetData?(): Promise<{ canceled: boolean }>;
    status(): Promise<LocalRuntimeStatus | null>;
    retry(): Promise<LocalRuntimeStatus>;
    select(kind: RuntimePathKind): Promise<LocalRuntimeStatus>;
    useEngine?(id: string): Promise<LocalRuntimeStatus>;
    removeFolder?(kind: "model_roots" | "engine_roots", index: number): Promise<LocalRuntimeStatus>;
  };
  appInfo(): Promise<{
    version: string;
    platform: string;
    packaged: boolean;
    security?: Record<string, unknown>;
  }>;
  settings: {
    status(): Promise<BridgeSettingsStatus>;
    setApiBaseUrl(url: string): Promise<BridgeSettingsStatus>;
    setToken(token: string): Promise<BridgeSettingsStatus>;
    clearToken(): Promise<BridgeSettingsStatus>;
  };
  api: {
    request<T>(
      method: "GET" | "POST",
      path: string,
      body?: unknown,
      idempotencyKey?: string | null,
    ): Promise<BridgeResponse<T>>;
    subscribeEvents(experimentId: string, lastEventId: number): Promise<string>;
    unsubscribeEvents(subscriptionId: string): Promise<void>;
    onEvent(listener: (event: BridgeEvent) => void): () => void;
  };
  saveReport(suggestedName: string, content: string): Promise<{ canceled: boolean; path?: string }>;
}

declare global {
  interface Window {
    labDesktop?: DesktopBridge;
  }
}
