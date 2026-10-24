import { recommendBuild, type HardwareProfile, type BuildRecommendation } from "./build-recommendation";
import { promises as fs } from "node:fs";
import path from "node:path";
import { createHash, randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import type { EngineCandidate, RuntimeStatus } from "./runtime-manager";

export type EngineFamily = "llamacpp" | "strata";
const REPOS: Record<EngineFamily, string> = { llamacpp: "ggml-org/llama.cpp", strata: "Niko1221/Strata" };
interface Asset { id: number; name: string; size: number; digest: string; url: string; download_size?: number }
export interface EngineRelease {
  engine_id: EngineFamily; version: string; tag: string; published: string;
  preview: boolean; installed_version: string | null; update: "available" | "current" | "unknown";
  assets: Asset[]; support?: Asset; page: string;
  dependencies?: Record<number, Asset[]>;
  recommendation?: BuildRecommendation;
}
export interface EngineUpdateStatus {
  enabled: boolean; checking: boolean; checked_at: string | null; error: string | null;
  releases: EngineRelease[]; operation: string | null;
  installation?: { engine_id: EngineFamily; asset_id: number; version: string; phase: "downloading" | "unpacking" | "complete" | "failed"; bytes_done: number; bytes_total: number };
  hardware?: HardwareProfile;
}

export function versionCompare(left: string, right: string): number | null {
  const parse = (value: string) => /^v?(\d+(?:\.\d+){1,3})(?:-([a-zA-Z0-9.-]+))?$/.exec(value);
  const a = parse(left); const b = parse(right);
  if (!a || !b) return null;
  const av = a[1]!.split(".").map(Number); const bv = b[1]!.split(".").map(Number);
  for (let i = 0; i < Math.max(av.length, bv.length); i++) {
    const difference = (av[i] ?? 0) - (bv[i] ?? 0);
    if (difference) return Math.sign(difference);
  }
  if (a[2] === b[2]) return 0;
  if (!a[2]) return 1;
  if (!b[2]) return -1;
  const ap = a[2].split("."); const bp = b[2].split(".");
  for (let i = 0; i < Math.max(ap.length, bp.length); i++) {
    const x = ap[i], y = bp[i];
    if (x === undefined) return -1;
    if (y === undefined) return 1;
    if (x === y) continue;
    const xn = /^\d+$/.test(x), yn = /^\d+$/.test(y);
    if (xn && yn) return Math.sign(Number(x) - Number(y));
    if (xn !== yn) return xn ? -1 : 1;
    return x < y ? -1 : 1;
  }
  return 0;
}

export function recommendedBuilds(builds: EngineCandidate[]): Set<string> {
  const result = new Set<string>();
  for (const family of ["llamacpp", "strata"] as const) {
    // Unknown versions and folder-name hints cannot establish which binary is latest.
    const known = builds.filter(b => b.engine_id === family && b.version && b.version_source !== "folder name (unverified)" && !b.missing.length);
    known.sort((a, b) => (versionCompare(b.version!, a.version!) ?? 0) || (b.build_number ?? 0) - (a.build_number ?? 0));
    if (known[0]) result.add(known[0].id);
  }
  return result;
}

function official(url: string, download = false): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && !parsed.username && !parsed.password && (!parsed.port || parsed.port === "443") && (download ? ["github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"].includes(parsed.hostname) : parsed.hostname === "api.github.com");
  } catch { return false; }
}

async function responseAt(url: string, signal: AbortSignal, download = false): Promise<Response> {
  for (let redirects = 0; redirects < 5; redirects++) {
    if (!official(url, download)) throw new Error("Untrusted release source");
    const response = await fetch(url, { redirect: "manual", signal, headers: { "User-Agent": "Inference-Lab-Desktop", Accept: download ? "application/octet-stream" : "application/vnd.github+json" } });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get("location"); await response.body?.cancel();
      if (!location) throw new Error("Invalid release redirect");
      url = new URL(location, url).href; continue;
    }
    if (!response.ok) throw new Error(response.status === 403 || response.status === 429 ? "Release service rate limit reached. Try later." : `Release service returned ${response.status}`);
    return response;
  }
  throw new Error("Too many release redirects");
}

async function boundedBody(response: Response, limit: number): Promise<Buffer> {
  const chunks: Uint8Array[] = []; let size = 0;
  if (!response.body) throw new Error("Empty release response");
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > limit) throw new Error("Release response exceeds size limit");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

export function parseRelease(family: EngineFamily, raw: unknown, arch = process.arch): EngineRelease {
  if (!raw || typeof raw !== "object") throw new Error("Invalid release metadata");
  const value = raw as Record<string, unknown>;
  if (value.draft || typeof value.tag_name !== "string" || !/^[A-Za-z0-9._-]{1,80}$/.test(value.tag_name) || !Array.isArray(value.assets)) throw new Error("Unsupported release metadata");
  const assets: Asset[] = [];
  for (const entry of value.assets.slice(0, 200)) {
    const a = entry as Record<string, unknown>;
    if (!Number.isSafeInteger(a.id) || typeof a.name !== "string" || !/^[A-Za-z0-9._-]{1,180}$/.test(a.name) || typeof a.size !== "number" || a.size <= 0 || a.size > 2 * 1024 ** 3 || typeof a.digest !== "string" || !/^sha256:[a-f0-9]{64}$/.test(a.digest) || typeof a.browser_download_url !== "string") continue;
    const prefix = `https://github.com/${REPOS[family]}/releases/download/`;
    if (!a.browser_download_url.toLowerCase().startsWith(prefix.toLowerCase()) || !official(a.browser_download_url, true) || !a.browser_download_url.endsWith("/" + a.name)) continue;
    assets.push({ id: a.id as number, name: a.name, size: a.size, digest: a.digest, url: a.browser_download_url });
  }
  const architecture = arch === "x64" ? /(?:x64|x86_64)/ : arch === "arm64" ? /arm64|aarch64/ : /(?!) /;
  const native = assets.filter(a => a.name.endsWith(".tar.gz") && /linux|ubuntu/.test(a.name) && architecture.test(a.name) && (family === "llamacpp" ? a.name.startsWith("llama-") && a.name.includes("-bin-") : a.name.startsWith("strata-engine-")));
  const versions = family === "strata" ? native.map(a => /^strata-engine-([0-9.]+)-/.exec(a.name)?.[1]).filter((v): v is string => !!v).sort((a, b) => versionCompare(b, a) ?? 0) : [];
  const version = versions[0] ?? value.tag_name;
  const filtered = family === "strata" ? native.filter(a => a.name.startsWith(`strata-engine-${version}-`)) : native;
  const support = assets.find(a => a.name === `strata-control-${version}-linux-${arch === "x64" ? "x86_64" : "aarch64"}.tar.gz`);
  const dependencies: Record<number, Asset[]> = {};
  const installable = filtered.filter(asset => {
    if (family !== "llamacpp" || !asset.name.includes("-cuda-")) return true;
    const runtime = assets.find(candidate => candidate.name === `cudart-${asset.name}`);
    if (!runtime) return false; // A CUDA archive alone is not a complete installation.
    dependencies[asset.id] = [runtime]; return true;
  });
  return { dependencies, engine_id: family, version, tag: value.tag_name, published: typeof value.published_at === "string" ? value.published_at.slice(0, 40) : "", preview: value.prerelease === true, installed_version: null, update: "unknown", assets: installable, support, page: `https://github.com/${REPOS[family]}/releases/tag/${value.tag_name}` };
}

export class EngineUpdates {
  private state: EngineUpdateStatus = { enabled: true, checking: false, checked_at: null, error: null, releases: [], operation: null };
  private hardwareTask: Promise<void> | null = null;
  private hardware: HardwareProfile = { architecture: process.arch, cpu_avx2: false, gpus: [], warnings: [] };
  private abortInstall: AbortController | null = null;
  cancel(): void { this.abortInstall?.abort(); }
  private checkTask: Promise<EngineUpdateStatus> | null = null;
  constructor(private readonly data: string, private readonly backend: string, private readonly current: () => RuntimeStatus, private readonly request = responseAt) {}
  status(): EngineUpdateStatus { return structuredClone({ ...this.state, hardware: this.hardware,
    releases: this.state.releases.map(release => ({ ...release, assets: release.assets.map(asset => ({ ...asset, download_size: asset.size + (release.support?.size ?? 0) + (release.dependencies?.[asset.id] ?? []).reduce((sum, item) => sum + item.size, 0) })), recommendation: recommendBuild(release, this.hardware) })) }); }
  detectHardware(): Promise<void> { return this.hardwareTask ??= this.probeHardware(); }
  private async probeHardware(): Promise<void> {
    try {
      const raw = await new Promise<string>((resolve, reject) => {
        const child = spawn(path.join(this.backend, "python/bin/python3"), ["-I", path.join(this.backend, "bootstrap.py"), "desktop-hardware"], { env: { PATH: "/usr/bin:/bin", LANG: "C.UTF-8" }, stdio: ["ignore", "pipe", "ignore"] });
        let output = "";
        const timer = setTimeout(() => { child.kill("SIGKILL"); reject(new Error("Hardware detection timed out")); }, 15_000);
        child.stdout.on("data", bytes => { output += bytes.toString(); if (output.length > 65536) child.kill("SIGKILL"); });
        child.once("error", error => { clearTimeout(timer); reject(error); });
        child.once("exit", code => { clearTimeout(timer); code === 0 && output.length <= 65536 ? resolve(output) : reject(new Error("Hardware detection unavailable")); });
      });
      const value = JSON.parse(raw);
      if (typeof value.architecture !== "string" || typeof value.cpu_avx2 !== "boolean" || !Array.isArray(value.gpus)) throw new Error("Invalid hardware response");
      this.hardware = { architecture: value.architecture.slice(0, 40), cpu_avx2: value.cpu_avx2, warnings: [],
        gpus: value.gpus.slice(0, 32).filter((gpu: Record<string, unknown>) => typeof gpu.name === "string" && typeof gpu.vendor === "string") };
    } catch { this.hardware = { architecture: process.arch, cpu_avx2: false, gpus: [], warnings: ["Hardware detection could not complete. Keep the current engine and restart the app to detect hardware again."] }; }
  }
  reportFailure(error: unknown): void { this.state.error = error instanceof Error ? error.message.slice(0, 500) : "Engine operation failed"; }
  async load(): Promise<void> {
    await this.detectHardware();
    try {
      const raw = JSON.parse(await fs.readFile(path.join(this.data, "engine-update-preferences.json"), "utf8"));
      if (typeof raw.enabled === "boolean") this.state.enabled = raw.enabled;
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") this.state.error = "Could not read update preferences"; }
  }
  async setEnabled(enabled: boolean): Promise<EngineUpdateStatus> {
    if (typeof enabled !== "boolean") throw new Error("Invalid update preference");
    await fs.mkdir(this.data, { recursive: true, mode: 0o700 });
    const file = path.join(this.data, "engine-update-preferences.json");
    await fs.writeFile(file + ".tmp", JSON.stringify({ enabled }), { mode: 0o600 });
    await fs.rename(file + ".tmp", file);
    this.state.enabled = enabled; return this.status();
  }
  check(): Promise<EngineUpdateStatus> {
    if (this.checkTask) return this.checkTask;
    this.checkTask = this.doCheck().finally(() => { this.checkTask = null; });
    return this.checkTask;
  }
  private async doCheck(): Promise<EngineUpdateStatus> {
    this.state.checking = true; this.state.error = null;
    const releases: EngineRelease[] = [];
    const errors: string[] = [];
    const builds = this.current().engine_candidates ?? [];
    const config = this.current().config;
    const families = (["llamacpp", "strata"] as const).filter(f => builds.some(b => b.engine_id === f) || (f === "llamacpp" ? config.llama_server_path : config.strata_path));
    await Promise.all(families.map(async family => {
      try {
        const signal = AbortSignal.timeout(20_000);
        const raw = JSON.parse((await boundedBody(await this.request(`https://api.github.com/repos/${REPOS[family]}/releases/latest`, signal), 4 * 1024 ** 2)).toString());
        const release = parseRelease(family, raw);
        // llama.cpp stable releases point to a matching binary nightly tag.
        if (family === "llamacpp" && !release.assets.length) {
          const pointer = raw.assets?.find((a: Record<string, unknown>) => a.name === "nightly-tag.txt");
          if (pointer && typeof pointer.digest === "string" && /^sha256:[a-f0-9]{64}$/.test(pointer.digest) && pointer.browser_download_url === `https://github.com/${REPOS[family]}/releases/download/${release.tag}/nightly-tag.txt`) {
            const bytes = await boundedBody(await this.request(pointer.browser_download_url, signal, true), 100);
            if (`sha256:${createHash("sha256").update(bytes).digest("hex")}` !== pointer.digest) throw new Error("Release pointer checksum mismatch");
            const tag = bytes.toString().trim();
            if (!/^b\d+$/.test(tag)) throw new Error("Invalid binary release tag");
            const binary = parseRelease(family, JSON.parse((await boundedBody(await this.request(`https://api.github.com/repos/${REPOS[family]}/releases/tags/${tag}`, signal), 4 * 1024 ** 2)).toString()));
            release.assets = binary.assets;
            release.dependencies = binary.dependencies;
          }
        }
        const known = builds.filter(b => b.engine_id === family && b.version && b.version_source !== "folder name (unverified)").map(b => b.version!).sort((a, b) => versionCompare(b, a) ?? 0);
        const selectedPath = family === "llamacpp" ? config.llama_server_path : config.strata_path;
        const selected = builds.find(b => (b.paths.llama_server_path ?? b.paths.strata_path) === selectedPath);
        release.installed_version = selectedPath ? selected?.version_source === "folder name (unverified)" ? null : selected?.version ?? null : known[0] ?? null;
        // Development builds can contain commits after a same-version stable
        // release. A version header alone cannot establish an upgrade direction.
        const installed = release.installed_version;
        const sameBaseDevelopment = installed?.includes("-dev") && installed.replace(/^v/, "").split("-")[0] === release.version.replace(/^v/, "");
        const difference = installed && !sameBaseDevelopment ? versionCompare(release.version, installed) : null;
        release.update = difference === null ? "unknown" : difference > 0 ? "available" : "current";
        releases.push(release);
      } catch (error) { errors.push(`${family === "llamacpp" ? "llama.cpp" : "Strata"}: ${error instanceof Error ? error.message : "Check failed"}`); }
    }));
    this.state.releases = releases.sort((a, b) => a.engine_id.localeCompare(b.engine_id));
    this.state.checked_at = new Date().toISOString(); this.state.checking = false;
    this.state.error = errors.join(" · ") || null;
    return this.status();
  }
  asset(family: unknown, id: unknown): { release: EngineRelease; asset: Asset } {
    const release = this.state.releases.find(r => r.engine_id === family);
    const asset = release?.assets.find(a => a.id === id);
    if (!release || !asset) throw new Error("Check releases and choose an offered Linux asset");
    if (family === "strata" && !release.support) throw new Error("This release has no matching verified Strata server bundle");
    return { release, asset };
  }
  async install(family: unknown, id: unknown): Promise<string> {
    if (this.state.operation) throw new Error("An engine operation is already in progress");
    const { release, asset } = this.asset(family, id);
    this.state.error = null;
    this.state.operation = "Preparing engine update";
    this.state.installation = { engine_id: release.engine_id, asset_id: asset.id, version: release.version, phase: "downloading", bytes_done: 0, bytes_total: 0 };
    this.abortInstall = new AbortController();
    const managed = path.join(this.data, "managed-engines");
    const stage = path.join(managed, "staging-" + randomBytes(12).toString("hex"));
    const target = path.join(managed, `${release.engine_id}-${asset.id}`);
    try {
      await fs.mkdir(managed, { recursive: true, mode: 0o700 });
      try { await fs.access(target); throw new Error("This asset is already installed. Rescan folders to use it."); }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
      await fs.mkdir(stage, { mode: 0o700 });
      const assets = [asset, ...(release.dependencies?.[asset.id] ?? []), ...(release.support ? [release.support] : [])];
      this.state.installation.bytes_total = assets.reduce((sum, item) => sum + item.size, 0);
      const space = await fs.statfs(managed);
      if (space.bavail * space.bsize < assets.reduce((n, a) => n + a.size, 0) + assets.length * 4 * 1024 ** 3) throw new Error("At least the download size plus 4 GiB per archive of free disk space is required");
      for (const [index, item] of assets.entries()) {
        this.state.installation.phase = "downloading";
        this.state.operation = `Downloading ${item.name}`;
        const archive = path.join(stage, `${index}.tar.gz`);
        const response = await this.request(item.url, AbortSignal.any([AbortSignal.timeout(15 * 60_000), this.abortInstall.signal]), true);
        const handle = await fs.open(archive, "wx", 0o600); const hash = createHash("sha256"); let size = 0;
        try {
          if (!response.body) throw new Error("Empty asset response");
          for await (const chunk of response.body) {
            size += chunk.length;
            if (size > item.size) throw new Error("Asset exceeds declared size");
            hash.update(chunk); await handle.writeFile(chunk);
            this.state.installation.bytes_done += chunk.length;
          }
        } finally { await handle.close(); }
        if (size !== item.size || `sha256:${hash.digest("hex")}` !== item.digest) throw new Error("Downloaded archive size or SHA-256 mismatch");
        this.state.installation.phase = "unpacking";
        this.state.operation = `Verifying and unpacking ${item.name}`;
        await this.extract(archive, path.join(stage, index ? release.engine_id === "strata" ? "control" : "runtime" : "engine"));
        await fs.unlink(archive);
      }
      const executable = await findFile(path.join(stage, "engine"), release.engine_id === "llamacpp" ? "llama-server" : "strata");
      if (!executable) throw new Error("Expected engine executable is missing from archive");
      if (release.dependencies?.[asset.id]?.length) await copyRuntimeLibraries(path.join(stage, "runtime"), path.dirname(executable));
      const header = { engine_id: release.engine_id, version: release.version, tag: release.tag, asset_id: asset.id, digest: asset.digest, installed_at: new Date().toISOString() };
      const build = path.basename(path.dirname(executable)) === "bin" ? path.dirname(path.dirname(executable)) : path.dirname(executable);
      await fs.writeFile(path.join(build, "lab-install.json"), JSON.stringify(header), { mode: 0o600 });
      if (release.engine_id === "strata") {
        const script = await findFile(path.join(stage, "control"), "server.py", "/serve/");
        const python = await findFile(path.join(stage, "control"), "python3", "/bin/");
        if (!script || !python) throw new Error("Strata server/interpreter layout is unsupported; current build is preserved");
        await fs.symlink(path.relative(stage, path.dirname(script)), path.join(stage, "serve"));
        await fs.symlink(path.relative(stage, path.dirname(path.dirname(python))), path.join(stage, "python"));
      }
      await fs.writeFile(path.join(stage, "lab-managed.json"), JSON.stringify(header), { mode: 0o600 });
      await fs.rename(stage, target);
      this.state.installation.phase = "complete";
      return managed;
    } catch (error) {
      if (this.state.installation) this.state.installation.phase = "failed";
      this.reportFailure(error); throw error;
    } finally {
      await fs.rm(stage, { recursive: true, force: true }); this.state.operation = null; this.abortInstall = null;
    }
  }
  private extract(archive: string, target: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const child = spawn(path.join(this.backend, "python/bin/python3"), ["-I", path.join(this.backend, "bootstrap.py"), "engine-archive", archive, target], { cwd: this.data, env: { PATH: "/usr/bin:/bin", LANG: "C.UTF-8" }, stdio: "ignore" });
      const signal = this.abortInstall?.signal;
      const abort = () => { child.kill("SIGKILL"); };
      signal?.addEventListener("abort", abort, { once: true });
      if (signal?.aborted) abort();
      let timedOut = false;
      const timer = setTimeout(() => { timedOut = true; child.kill("SIGKILL"); }, 120_000);
      child.once("error", () => { clearTimeout(timer); reject(new Error("Bundled archive extractor could not start")); });
      child.once("exit", code => { clearTimeout(timer); signal?.removeEventListener("abort", abort); code === 0 && !signal?.aborted ? resolve() : reject(new Error(timedOut ? "Archive extraction timed out" : signal?.aborted ? "Engine installation cancelled" : "Archive failed safe extraction checks")); });
    });
  }
}

async function findFile(root: string, name: string, pathPart = ""): Promise<string | null> {
  const queue = [root]; let count = 0;
  while (queue.length && count++ < 20_000) {
    const directory = queue.shift()!;
    for (const item of await fs.readdir(directory, { withFileTypes: true })) {
      const file = path.join(directory, item.name);
      if (item.isDirectory()) queue.push(file);
      else if ((item.isFile() || item.isSymbolicLink()) && item.name === name && file.includes(pathPart)) {
        const resolved = await fs.realpath(file);
        if (resolved.startsWith(root + path.sep) && (await fs.stat(resolved)).isFile()) return file;
      }
    }
  }
  return null;
}

export async function removableBuild(build: EngineCandidate, status: RuntimeStatus, managed: string): Promise<string> {
  const executable = build.paths.llama_server_path ?? build.paths.strata_path;
  if (!executable) throw new Error("Unknown engine executable");
  if (Object.values(status.config).some(value => typeof value === "string" && value === executable)) throw new Error("Select another build before removing this one");
  const roots = [...(status.config.engine_roots ?? [])];
  const resolved = await fs.realpath(executable);
  let directory = path.basename(path.dirname(resolved)) === "bin" ? path.dirname(path.dirname(resolved)) : path.dirname(resolved);
  if (resolved.startsWith(managed + path.sep)) {
    const relative = path.relative(managed, resolved).split(path.sep)[0]!;
    if (!/^(llamacpp|strata)-\d+$/.test(relative)) throw new Error("Not a managed engine installation");
    directory = path.join(managed, relative);
    await fs.access(path.join(directory, "lab-managed.json"));
  } else {
    if (path.basename(path.dirname(directory)) !== "linux" || path.basename(path.dirname(path.dirname(directory))) !== "builds") throw new Error("Only isolated builds/linux/<build> directories can be removed. Shared source/runtime folders are protected.");
    if (!(await Promise.all(roots.map(root => fs.realpath(root)))).some(root => directory.startsWith(root + path.sep))) throw new Error("Build is outside selected inference folders");
  }
  const protectedPaths = [...status.config.model_roots, ...Object.entries(status.config).filter(([key]) => !key.endsWith("roots")).map(([, value]) => value).filter((v): v is string => typeof v === "string"), ...(status.engine_candidates ?? []).filter(b => b.id !== build.id).flatMap(b => Object.values(b.paths))];
  for (const entry of protectedPaths) {
    const real = await fs.realpath(entry).catch(() => entry);
    if (real === directory || real.startsWith(directory + path.sep) || directory.startsWith(real + path.sep)) throw new Error("This directory is shared with selected models or another engine. It cannot be removed.");
  }
  // Removing an isolated build must never take model weights with it.
  const queue = [directory]; let count = 0;
  while (queue.length) {
    if (++count > 20_000) throw new Error("Build directory is too large to verify safely");
    const current = queue.shift()!;
    for (const entry of await fs.readdir(current, { withFileTypes: true })) {
      if (/\.(gguf|safetensors)$/i.test(entry.name)) throw new Error("Model files found inside build; removal refused");
      if (entry.isDirectory()) queue.push(path.join(current, entry.name));
    }
  }
  return directory;
}

async function copyRuntimeLibraries(root: string, destination: string): Promise<void> {
  const queue = [root]; let visited = 0;
  while (queue.length) {
    if (++visited > 20000) throw new Error("Runtime library archive is too large");
    const current = queue.shift()!;
    for (const entry of await fs.readdir(current, { withFileTypes: true })) {
      const file = path.join(current, entry.name);
      if (entry.isDirectory()) { queue.push(file); continue; }
      if (!/\.so(?:\.[0-9.]+)?$/.test(entry.name)) continue;
      const resolved = await fs.realpath(file);
      if (!resolved.startsWith(root + path.sep)) throw new Error("Unsafe runtime library path");
      const target = path.join(destination, entry.name);
      if (entry.isSymbolicLink()) await fs.symlink(path.basename(resolved), target);
      else await fs.copyFile(file, target, 1);
    }
  }
}
