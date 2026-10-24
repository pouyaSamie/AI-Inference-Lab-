import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ spawn: vi.fn(), available: vi.fn(), backend: vi.fn(), encrypt: vi.fn(), decrypt: vi.fn() }));
vi.mock("electron", () => ({ safeStorage: { isEncryptionAvailable: mocks.available, getSelectedStorageBackend: mocks.backend, encryptString: mocks.encrypt, decryptString: mocks.decrypt } }));
vi.mock("node:child_process", () => ({ default: { spawn: mocks.spawn }, spawn: mocks.spawn }));
import { cleanEnvironment, RuntimeManager, validateRuntimeConfig } from "./runtime-manager";
import type { SettingsStore } from "./settings";

class FakeChild extends EventEmitter {
  stdin = new PassThrough();
  channel = new PassThrough();
  stdio = [this.stdin, null, null, this.channel];
  exitCode: number | null = null;
  constructor() {
    super();
    this.stdin.on("finish", () => { this.exitCode = 0; this.emit("exit", 0); this.channel.end(); });
  }
}

describe("packaged local runtime boundary", () => {
  let temp: string;
  let manager: RuntimeManager | null;
  beforeEach(async () => {
    temp = await fs.mkdtemp(path.join(os.tmpdir(), "lab-runtime-manager-"));
    manager = null;
    mocks.available.mockReturnValue(false);
    mocks.backend.mockReturnValue("basic_text");
    await fs.mkdir(path.join(temp, "backend/python/bin"), { recursive: true });
    await fs.writeFile(path.join(temp, "backend/python/bin/python3"), "test executable placeholder");
  });
  afterEach(async () => { await manager?.stop(); await fs.rm(temp, { recursive: true, force: true }); });

  it("drops inherited credentials, Python hooks, proxies and development overrides", () => {
    expect(cleanEnvironment({ HOME: "/home/operator", LAB_OPERATOR_TOKEN: "secret", PYTHONPATH: "/evil", LD_PRELOAD: "/evil.so", HTTPS_PROXY: "http://proxy", LAB_DESKTOP_DEV_SERVER: "http://localhost:1", PATH: "/evil" })).toEqual({ HOME: "/home/operator", PATH: "/usr/bin:/bin", LANG: "C.UTF-8" });
  });
  it("accepts only known absolute configuration paths", () => {
    expect(validateRuntimeConfig({ model_roots: ["/models"], llama_server_path: "/opt/llama-server" })).toMatchObject({ model_roots: ["/models"] });
    for (const raw of [{ model_roots: ["relative"] }, { model_roots: ["/models/../private"] }, { model_roots: [], command: "sh" }, { model_roots: [], strata_python: "/bin/python\n" }, { model_roots: "wrong" }]) expect(() => validateRuntimeConfig(raw)).toThrow();
  });
  it("starts once, consumes private status, hides secrets and shuts down over EOF", async () => {
    const child = new FakeChild();
    mocks.spawn.mockReturnValue(child);
    const settings = { setManagedConnection: vi.fn(), clearManagedConnection: vi.fn() };
    manager = new RuntimeManager(path.join(temp, "backend"), path.join(temp, "data"), settings as unknown as SettingsStore);
    await Promise.all([manager.start(), manager.start()]);
    expect(mocks.spawn).toHaveBeenCalledTimes(1);
    const payload = JSON.parse(child.stdin.read().toString());
    expect(payload.secrets.operator.length).toBe(64);
    expect(payload.config.worker_id).toBe("desktop-local");
    expect(manager.status().secure_storage).toBe(false);
    expect(JSON.stringify(manager.status())).not.toContain(payload.secrets.operator);
    child.channel.write(JSON.stringify({ state: "ready", message: "Ready", url: "http://127.0.0.1:45678" }) + "\n");
    expect(manager.status().state).toBe("ready");
    expect(settings.setManagedConnection).toHaveBeenCalledWith("http://127.0.0.1:45678", payload.secrets.operator);
    await manager.stop();
    expect(child.exitCode).toBe(0);
    expect(manager.status().state).toBe("stopped");
    expect(settings.clearManagedConnection).toHaveBeenCalled();
    await expect(fs.access(path.join(temp, "data/worker-pepper.enc"))).rejects.toThrow();
  });
  it("falls back to session credentials when keyring encryption throws", async () => {
    mocks.available.mockReturnValue(true); mocks.backend.mockReturnValue("gnome_libsecret");
    mocks.encrypt.mockImplementation(() => { throw new Error("keyring locked"); });
    const child = new FakeChild(); mocks.spawn.mockReturnValue(child);
    manager = new RuntimeManager(path.join(temp, "backend"), path.join(temp, "data"), { clearManagedConnection: vi.fn() } as unknown as SettingsStore);
    await manager.start();
    expect(manager.status().secure_storage).toBe(false);
    expect(manager.status().state).toBe("starting");
    await expect(fs.access(path.join(temp, "data/worker-pepper.enc"))).rejects.toThrow();
  });
  it("reports missing bundled runtime as an actionable failure", async () => {
    manager = new RuntimeManager(path.join(temp, "missing"), path.join(temp, "data"), { clearManagedConnection: vi.fn() } as unknown as SettingsStore);
    await manager.start();
    expect(manager.status().state).toBe("error");
  });
  it("selects only discovered builds and persists folder edits across restart", async () => {
    mocks.spawn.mockImplementation(() => new FakeChild());
    manager = new RuntimeManager(path.join(temp, "backend"), path.join(temp, "data"), { setManagedConnection: vi.fn(), clearManagedConnection: vi.fn() } as unknown as SettingsStore);
    await manager.start();
    await manager.select("engine_roots", temp);
    const child = mocks.spawn.mock.results.at(-1)!.value as FakeChild;
    const id = "a".repeat(24);
    child.channel.write(JSON.stringify({ state: "needs_configuration", message: "Choose a build", url: "http://127.0.0.1:45678", engine_candidates: [{ id, engine_id: "llamacpp", label: "Test build", paths: { llama_server_path: path.join(temp, "bin/llama-server") }, missing: [] }] }) + "\n");
    await expect(manager.useEngine("untrusted-path")).rejects.toThrow("discovered");
    await manager.useEngine(id);
    expect(JSON.parse(await fs.readFile(path.join(temp, "data/config.json"), "utf8")).llama_server_path).toBe(path.join(temp, "bin/llama-server"));
    await expect(manager.removeFolder("engine_roots", -1)).rejects.toThrow("Invalid");
    await manager.removeFolder("engine_roots", 0);
    const saved = JSON.parse(await fs.readFile(path.join(temp, "data/config.json"), "utf8"));
    expect(saved.engine_roots).toEqual([]);
    expect(saved.llama_server_path).toBeUndefined();
  });
});
