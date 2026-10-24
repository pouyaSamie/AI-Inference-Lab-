import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
import { createHash } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EngineUpdates, parseRelease, recommendedBuilds, removableBuild, versionCompare } from "./engine-updates";
import type { EngineCandidate, RuntimeStatus } from "./runtime-manager";

const bytes = Buffer.from("archive fixture, never executed");
const digest = "sha256:" + createHash("sha256").update(bytes).digest("hex");
function metadata(family = "llamacpp", tag = "v0.7.0") {
  const repo = family === "llamacpp" ? "ggml-org/llama.cpp" : "Niko1221/Strata";
  const name = family === "llamacpp" ? "llama-b123-bin-ubuntu-x64.tar.gz" : "strata-engine-0.1.47-linux-x86_64-cuda-cuda12.tar.gz";
  return { tag_name: tag, published_at: "2026-10-20T00:00:00Z", prerelease: false, assets: [{ id: 123, name, size: bytes.length, digest, browser_download_url: `https://github.com/${repo}/releases/download/${tag}/${name}` }] };
}
function build(id: string, version: string, extra: Partial<EngineCandidate> = {}): EngineCandidate {
  return { id, version, engine_id: "llamacpp", label: id, paths: {}, missing: [], version_source: "build metadata", ...extra };
}
describe("engine release manager", () => {
  let temp: string;
  beforeEach(async () => { temp = await fs.mkdtemp(path.join(os.tmpdir(), "lab-engine-updates-")); });
  afterEach(async () => { await fs.rm(temp, { recursive: true, force: true }); });
  const current = (): RuntimeStatus => ({ managed: true, state: "ready", message: "Ready", config: { model_roots: [] }, secure_storage: false, engine_candidates: [build("old", "0.6.0")] });
  it("recommends the newest known complete build per engine and excludes folder guesses", () => {
    expect(versionCompare("0.1.47", "0.1.9")).toBe(1);
    expect(versionCompare("0.7.0", "0.7.0-dev")).toBe(1);
    expect(versionCompare("b123", "0.7.0")).toBeNull();
    const found = recommendedBuilds([build("old", "0.6.0"), build("new", "0.7.0-dev", { build_number: 700 }), build("newer", "0.7.0-dev", { build_number: 701 }), build("guess", "99.0.0", { version_source: "folder name (unverified)" }), build("incomplete", "1.0.0", { missing: ["llama-bench"] })]);
    expect([...found]).toEqual(["newer"]);
  });
  it("filters assets by host architecture, official source and checksum", () => {
    const value = metadata();
    value.assets.push({ ...value.assets[0]!, id: 124, digest: "", browser_download_url: "https://evil.invalid/x" });
    expect(parseRelease("llamacpp", value, "x64").assets.map(a => a.id)).toEqual([123]);
    expect(parseRelease("llamacpp", value, "arm64").assets).toEqual([]);
    expect(parseRelease("strata", metadata("strata", "v0.2.2")).version).toBe("0.1.47");
  });
  it("checks metadata without downloading an engine and saves startup preference", async () => {
    const request = vi.fn(async (_url: string) => new Response(JSON.stringify(metadata())));
    const manager = new EngineUpdates(temp, "/bundled", current, request);
    const result = await manager.check();
    expect(result.releases[0]?.update).toBe("available");
    expect(request).toHaveBeenCalledTimes(1);
    expect(request.mock.calls[0]?.[0]).toBe("https://api.github.com/repos/ggml-org/llama.cpp/releases/latest");
    await manager.setEnabled(false);
    const reopened = new EngineUpdates(temp, "/bundled", current, request); await reopened.load();
    expect(reopened.status().enabled).toBe(false);
  });
  it("detects hardware once per app session and reuses it for subsequent checks", async () => {
    const manager = new EngineUpdates(temp, "/bundled", current, async () => new Response(JSON.stringify(metadata())));
    const probe = vi.spyOn(manager as unknown as { probeHardware(): Promise<void> }, "probeHardware").mockResolvedValue();
    await Promise.all([manager.detectHardware(), manager.detectHardware()]);
    await manager.check(); await manager.check();
    expect(probe).toHaveBeenCalledTimes(1);
  });
  it("reports failed/offline checks without inventing an update", async () => {
    const manager = new EngineUpdates(temp, "/bundled", current, async () => { throw new Error("Offline"); });
    const result = await manager.check();
    expect(result.error).toContain("Offline"); expect(result.releases).toEqual([]);
    await expect(manager.install("llamacpp", 999)).rejects.toThrow("offered");
  });
  it("verifies a stable release's pointer before offering its binary assets", async () => {
    const pointer = Buffer.from("b123\n");
    const stable = { ...metadata(), assets: [{ id: 321, name: "nightly-tag.txt", size: pointer.length, digest: "sha256:" + createHash("sha256").update(pointer).digest("hex"), browser_download_url: "https://github.com/ggml-org/llama.cpp/releases/download/v0.7.0/nightly-tag.txt" }] };
    const request = vi.fn(async (url: string) => new Response(url.endsWith("nightly-tag.txt") ? pointer : JSON.stringify(url.endsWith("/latest") ? stable : metadata("llamacpp", "b123"))));
    const manager = new EngineUpdates(temp, "/bundled", current, request);
    const result = await manager.check();
    expect(result.error).toBeNull();
    expect(result.releases[0]?.version).toBe("v0.7.0");
    expect(result.releases[0]?.assets[0]?.id).toBe(123);
    expect(request).toHaveBeenCalledTimes(3);
  });
  it("cancels an active download and removes staging before returning", async () => {
    let started!: () => void;
    const ready = new Promise<void>(resolve => { started = resolve; });
    const manager = new EngineUpdates(temp, "/bundled", current, async (url, signal) => {
      if (url.includes("api.github.com")) return new Response(JSON.stringify(metadata()));
      started();
      return new Promise<Response>((_resolve, reject) => signal.addEventListener("abort", () => reject(new Error("Cancelled")), { once: true }));
    });
    await manager.check();
    const installation = manager.install("llamacpp", 123);
    await ready; manager.cancel();
    await expect(installation).rejects.toThrow("Cancelled");
    expect(manager.status().installation?.phase).toBe("failed");
    expect(manager.status().operation).toBeNull();
    expect(await fs.readdir(path.join(temp, "managed-engines"))).toEqual([]);
  });
  it("installs an explicitly chosen checksum-verified asset side by side without execution", async () => {
    const request = vi.fn(async (url: string) => new Response(url.includes("api.github.com") ? JSON.stringify(metadata()) : bytes));
    const manager = new EngineUpdates(temp, "/bundled", current, request);
    await manager.check();
    const extract = vi.spyOn(manager as unknown as { extract(archive: string, target: string): Promise<void> }, "extract").mockImplementation(async (_archive, target) => {
      await fs.mkdir(path.join(target, "bin"), { recursive: true });
      await fs.writeFile(path.join(target, "bin/llama-server"), "never executed");
    });
    const root = await manager.install("llamacpp", 123);
    expect(extract).toHaveBeenCalledOnce();
    const record = JSON.parse(await fs.readFile(path.join(root, "llamacpp-123/lab-managed.json"), "utf8"));
    expect(record.digest).toBe(digest); expect(manager.status().operation).toBeNull();
    expect(manager.status().installation).toMatchObject({ phase: "complete", asset_id: 123, bytes_done: bytes.length, bytes_total: bytes.length });
    await expect(manager.install("llamacpp", 123)).rejects.toThrow("already installed");
  });
  it("cleans staging and preserves installed builds on corrupt download", async () => {
    const manager = new EngineUpdates(temp, "/bundled", current, async url => new Response(url.includes("api.github.com") ? JSON.stringify(metadata()) : "corrupt"));
    await manager.check();
    await expect(manager.install("llamacpp", 123)).rejects.toThrow("mismatch");
    expect(await fs.readdir(path.join(temp, "managed-engines"))).toEqual([]);
    expect(manager.status().operation).toBeNull();
  });
  it("allows only isolated inactive builds and refuses model/shared/selected directories", async () => {
    const root = path.join(temp, "inference"); const directory = path.join(root, "llama/builds/linux/old");
    await fs.mkdir(path.join(directory, "bin"), { recursive: true });
    const executable = path.join(directory, "bin/llama-server"); await fs.writeFile(executable, "binary");
    const old = build("old", "0.6.0", { paths: { llama_server_path: executable } });
    const status = { ...current(), engine_candidates: [old], config: { model_roots: [], engine_roots: [root] } };
    expect(await removableBuild(old, status, path.join(temp, "managed"))).toBe(directory);
    await expect(removableBuild(old, { ...status, config: { ...status.config, llama_server_path: executable } }, "/managed")).rejects.toThrow("another build");
    await fs.writeFile(path.join(directory, "model.gguf"), "model");
    await expect(removableBuild(old, status, "/managed")).rejects.toThrow("Model files");
  });
});
