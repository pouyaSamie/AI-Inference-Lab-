import { spawn, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { createInterface } from "node:readline";
import type { Readable } from "node:stream";
import { recommendedBuilds } from "./engine-updates";
import { safeStorage } from "electron";
import type { SettingsStore } from "./settings";
import { validateApiBaseUrl } from "./security";

export const PATH_KINDS = ["model_roots", "engine_roots", "llama_server_path", "llama_bench_path", "llama_lib_dir", "strata_path", "strata_server_script", "strata_python"] as const;
export type PathKind = typeof PATH_KINDS[number];
export type RuntimeConfig = Partial<Record<Exclude<PathKind, "model_roots" | "engine_roots">, string>> & { model_roots: string[]; engine_roots?: string[] };
export interface EngineCandidate {
  id: string;
  engine_id: "llamacpp" | "strata";
  label: string;
  paths: Partial<Record<Exclude<PathKind, "model_roots" | "engine_roots">, string>>;
  missing: string[];
  recommended?: boolean;
  version?: string | null;
  build_number?: number | null;
  version_source?: string | null;
}
export interface VerificationProgress { state: string; model_id?: string | null; bytes_done: number; bytes_total: number; files_done: number; files_total: number; current_file?: string; current_path?: string }
export interface InventorySummary { verification?: VerificationProgress; models: number; engines: number; gpus: number; verified_models: number; warnings: string[] }
export interface RuntimeStatus {
  managed: true;
  state: "stopped" | "starting" | "ready" | "needs_configuration" | "error";
  message: string;
  config: RuntimeConfig;
  secure_storage: boolean;
  inventory?: InventorySummary;
  engine_candidates?: EngineCandidate[];
}

export function cleanEnvironment(source: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  const result: NodeJS.ProcessEnv = { PATH: "/usr/bin:/bin", LANG: "C.UTF-8" };
  for (const name of ["HOME", "USER", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"])
    if (source[name]) result[name] = source[name];
  return result;
}

export function validateRuntimeConfig(raw: unknown): RuntimeConfig {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("Invalid local configuration");
  const value = raw as Record<string, unknown>;
  if (Object.keys(value).some((key) => !PATH_KINDS.includes(key as PathKind))) throw new Error("Unknown configuration field");
  const absolute = (entry: unknown): entry is string => typeof entry === "string" && path.isAbsolute(entry) && entry.length <= 4096 && !/[\u0000-\u001f\u007f]/.test(entry) && !entry.split(path.sep).includes("..");
  if (!Array.isArray(value.model_roots) || value.model_roots.length > 16 || !value.model_roots.every(absolute)) throw new Error("Select valid absolute model directories");
  if (value.engine_roots !== undefined && (!Array.isArray(value.engine_roots) || value.engine_roots.length > 16 || !value.engine_roots.every(absolute))) throw new Error("Select valid absolute inference directories");
  for (const key of PATH_KINDS)
    if (key !== "model_roots" && key !== "engine_roots" && value[key] !== undefined && !absolute(value[key])) throw new Error(`Invalid ${key}`);
  return value as RuntimeConfig;
}

export class RuntimeManager {
  private child: ChildProcess | null = null;
  private operation: Promise<void> | null = null;
  private stopOperation: Promise<void> | null = null;
  private config: RuntimeConfig = { model_roots: [] };
  private inventory?: InventorySummary;
  private candidates: EngineCandidate[] = [];
  private state: RuntimeStatus["state"] = "stopped";
  private message = "Local runtime stopped";
  private secureStorage = false;
  private sessionPepper = randomBytes(32).toString("hex");
  constructor(private readonly backend: string, private readonly data: string, private readonly settings: SettingsStore) {}

  status(): RuntimeStatus {
    return { managed: true, state: this.state, message: this.message, config: { ...this.config, model_roots: [...this.config.model_roots] }, secure_storage: this.secureStorage, inventory: this.inventory, engine_candidates: this.candidates.map(build => ({ ...build, recommended: recommendedBuilds(this.candidates).has(build.id) })) };
  }

  private async pepper(): Promise<string> {
    try { this.secureStorage = safeStorage.isEncryptionAvailable() && safeStorage.getSelectedStorageBackend() !== "basic_text"; }
    catch { this.secureStorage = false; }
    if (!this.secureStorage) return this.sessionPepper;
    const file = path.join(this.data, "worker-pepper.enc");
    try { return safeStorage.decryptString(await fs.readFile(file)); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        // Preserve unreadable key material. Start an independent enrollment for
        // this session rather than changing the pepper for existing identities.
        this.secureStorage = false;
        return this.sessionPepper;
      }
      try {
        const encrypted = safeStorage.encryptString(this.sessionPepper);
        await fs.writeFile(`${file}.tmp`, encrypted, { mode: 0o600 });
        await fs.rename(`${file}.tmp`, file);
      } catch { this.secureStorage = false; }
      return this.sessionPepper;
    }
  }

  start(): Promise<void> {
    if (this.stopOperation) return this.stopOperation.then(() => this.start());
    if (this.operation) return this.operation;
    if (this.child) return Promise.resolve();
    this.operation = this.launch().catch((error: unknown) => {
      this.state = "error";
      this.message = error instanceof Error ? error.message.slice(0, 400) : "Could not start local runtime";
    }).finally(() => { this.operation = null; });
    return this.operation;
  }

  private async launch(): Promise<void> {
    this.state = "starting";
    this.message = "Preparing local lab";
    await fs.mkdir(this.data, { recursive: true, mode: 0o700 });
    await fs.chmod(this.data, 0o700);
    try { this.config = validateRuntimeConfig(JSON.parse(await fs.readFile(path.join(this.data, "config.json"), "utf8"))); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
    const pepper = await this.pepper();
    const operator = randomBytes(32).toString("hex");
    const secret = { operator, optimizer: randomBytes(32).toString("hex"), enrollment: randomBytes(32).toString("hex"), pepper };
    const python = path.join(this.backend, "python/bin/python3");
    await fs.access(python);
    const child = spawn(python, ["-I", path.join(this.backend, "bootstrap.py"), "supervisor"], {
      cwd: this.data, env: cleanEnvironment(process.env), stdio: ["pipe", "ignore", "ignore", "pipe"],
    });
    this.child = child;
    child.on("error", () => {
      this.state = "error";
      this.message = "Bundled runtime could not start. Reinstall the package or inspect file permissions.";
      this.child = null;
    });
    child.on("exit", () => {
      if (this.child !== child) return;
      this.child = null;
      this.settings.clearManagedConnection();
      if (this.state !== "stopped" && this.state !== "error") {
        this.state = "error";
        this.message = "Local runtime stopped unexpectedly. Retry from Settings.";
      }
    });
    const channel = child.stdio[3] as Readable;
    const lines = createInterface({ input: channel });
    lines.on("line", (line: string) => {
      if (this.child !== child || line.length > 131072) return;
      try {
        const message = JSON.parse(line) as { state: string; message: string; url: string; inventory?: InventorySummary; engine_candidates?: EngineCandidate[] };
        if (!["starting", "ready", "needs_configuration", "error"].includes(message.state) || typeof message.message !== "string") return;
        if (message.inventory && [message.inventory.models, message.inventory.engines, message.inventory.gpus, message.inventory.verified_models].every((n) => Number.isSafeInteger(n) && n >= 0)) this.inventory = message.inventory;
        if (Array.isArray(message.engine_candidates)) this.candidates = message.engine_candidates.filter((candidate) => {
          if (!/^[a-f0-9]{24}$/.test(candidate.id) || !["llamacpp", "strata"].includes(candidate.engine_id) || typeof candidate.label !== "string" || !Array.isArray(candidate.missing)) return false;
          try { validateRuntimeConfig({ model_roots: [], ...candidate.paths }); return true; } catch { return false; }
        }).slice(0, 24);
        this.state = message.state as RuntimeStatus["state"];
        this.message = message.message.slice(0, 400);
        const url = validateApiBaseUrl(message.url);
        if (url.ok && url.value && new URL(url.value).hostname === "127.0.0.1") this.settings.setManagedConnection(url.value, operator);
      } catch { this.state = "error"; this.message = "Invalid local runtime startup response"; }
    });
    child.stdin?.on("error", () => undefined);
    child.stdin?.write(`${JSON.stringify({ root: this.data, migrations: path.join(this.backend, "migrations"), secrets: secret, config: { ...this.config, worker_id: "desktop-local" } })}\n`);
  }

  stop(): Promise<void> {
    if (this.stopOperation) return this.stopOperation;
    this.stopOperation = this.shutdown().finally(() => { this.stopOperation = null; });
    return this.stopOperation;
  }

  private async shutdown(): Promise<void> {
    if (this.operation) await this.operation;
    this.state = "stopped";
    this.message = "Local runtime stopped";
    this.settings.clearManagedConnection();
    const child = this.child;
    if (!child) return;
    // EOF is the supervisor's orderly shutdown command, also used on parent crash.
    child.stdin?.end();
    await new Promise<void>((resolve, reject) => {
      if (child.exitCode !== null) { resolve(); return; }
      const timeout = setTimeout(() => {
        this.state = "error";
        this.message = "Shutdown is still in progress. Wait before retrying.";
        reject(new Error(this.message));
      }, 150_000);
      child.once("exit", () => { clearTimeout(timeout); resolve(); });
    });
  }

  async retry(): Promise<void> { await this.stop(); await this.start(); }

  async select(kind: PathKind, selected: string): Promise<void> {
    const previous = this.config;
    selected = await fs.realpath(selected);
    const next = validateRuntimeConfig({ ...previous, [kind]: kind === "model_roots" || kind === "engine_roots" ? [...new Set([...(previous[kind] ?? []), selected])] : selected });
    const stat = await fs.stat(selected);
    if (["model_roots", "engine_roots", "llama_lib_dir"].includes(kind) ? !stat.isDirectory() : !stat.isFile()) throw new Error("Selected path has the wrong type");
    if (["llama_server_path", "llama_bench_path", "strata_path", "strata_python"].includes(kind)) await fs.access(selected, fs.constants.X_OK);
    await this.saveAndRestart(next);
  }

  async useEngine(id: unknown): Promise<void> {
    const candidate = this.candidates.find((item) => item.id === id);
    if (!candidate) throw new Error("Choose a discovered engine build");
    const cleared = { ...this.config };
    for (const key of PATH_KINDS) {
      if (candidate.engine_id === "llamacpp" ? key.startsWith("llama_") : key.startsWith("strata_")) delete cleared[key];
    }
    await this.saveAndRestart(validateRuntimeConfig({ ...cleared, ...candidate.paths }));
  }

  async removeFolder(kind: "model_roots" | "engine_roots", index: number): Promise<void> {
    const roots = this.config[kind] ?? [];
    if (!Number.isInteger(index) || index < 0 || index >= roots.length) throw new Error("Invalid folder selection");
    const removed = roots[index]!;
    const next = { ...this.config, [kind]: roots.filter((_, at) => at !== index) };
    if (kind === "engine_roots") {
      for (const key of PATH_KINDS) {
        if (key === "model_roots" || key === "engine_roots") continue;
        if (next[key]?.startsWith(removed + path.sep)) delete next[key];
      }
    }
    await this.saveAndRestart(validateRuntimeConfig(next));
  }

  private async saveAndRestart(next: RuntimeConfig): Promise<void> {
    await this.stop();
    await fs.writeFile(path.join(this.data, "config.json.tmp"), `${JSON.stringify(next, null, 2)}\n`, { mode: 0o600 });
    await fs.rename(path.join(this.data, "config.json.tmp"), path.join(this.data, "config.json"));
    this.config = next;
    await this.start();
  }
}
