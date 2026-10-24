import { promises as fs } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

const runtimeNames = new Set([
  "controller.sqlite3", "controller.sqlite3-wal", "controller.sqlite3-shm",
  "optuna.sqlite3", "optuna.sqlite3-wal", "optuna.sqlite3-shm",
  "worker", "artifacts", "backups", "config.json", "config.json.tmp", "runtime.lock",
  "worker-pepper.enc", "worker-pepper.enc.tmp", "engine-update-preferences.json", "engine-update-preferences.json.tmp",
]);
const overlaps = (a: string, b: string) => a === b || a.startsWith(b + path.sep) || b.startsWith(a + path.sep);
async function exists(file: string) { try { return await fs.lstat(file); } catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return null; throw error; } }

/** Only app-owned lab records move. Engine/model roots and unknown files never do. */
export async function resetManagedData(options: {
  userData: string; protectedPaths: string[];
  stop(): Promise<void>; clearBrowserData(): Promise<void>; trash(folder: string): Promise<void>;
}): Promise<void> {
  const root = await fs.realpath(options.userData);
  const lab = path.join(root, "local-lab");
  const labStat = await exists(lab);
  if (labStat?.isSymbolicLink() || labStat && !labStat.isDirectory()) throw new Error("Local lab data must be an owned directory");
  const targets: { source: string; relative: string }[] = [];
  for (const name of labStat ? await fs.readdir(lab) : []) {
    if (runtimeNames.has(name) || /^runtime\.log(?:\.\d+)?$/.test(name)) targets.push({ source: path.join(lab, name), relative: path.join("local-lab", name) });
  }
  for (const name of ["operator-token.bin", "operator-token.bin.tmp", "desktop-events.log", "desktop-events.log.1"]) {
    const source=path.join(root,name); if(await exists(source))targets.push({source,relative:name});
  }
  const protectedPaths = await Promise.all(options.protectedPaths.map(async value => fs.realpath(value).catch(() => path.resolve(value))));
  for (const target of targets) {
    if ((await fs.lstat(target.source)).isSymbolicLink()) throw new Error("Reset refuses symlinked lab records");
    if (protectedPaths.some(value => overlaps(value, target.source))) throw new Error("A model or engine path overlaps lab data. Move it outside the lab data directory before resetting.");
  }
  await options.stop(); // Caller must also verify a reachable idle controller before entering.
  const holding = path.join(root, `reset-recovery-${randomUUID()}`);
  await fs.mkdir(holding, { mode: 0o700 });
  const moved: { source: string; destination: string }[] = [];
  try {
    for (const target of targets) {
      // Recheck after shutdown; only the validated entry itself is moved, never its target.
      const stat=await exists(target.source); if(!stat)continue;
      if(stat.isSymbolicLink())throw new Error("Lab data changed during reset");
      const destination=path.join(holding,target.relative);
      await fs.mkdir(path.dirname(destination),{recursive:true,mode:0o700});
      await fs.rename(target.source,destination);moved.push({source:target.source,destination});
    }
    await options.clearBrowserData();
    await options.trash(holding); // Recoverable OS Trash; no recursive deletion of the only store copy.
  } catch (error) {
    const failures: string[]=[];
    for (const item of moved.reverse()) {
      try { if(await exists(item.source))throw new Error("Original path occupied");await fs.rename(item.destination,item.source); }
      catch { failures.push(item.destination); }
    }
    if(failures.length)throw new Error("Reset failed. Data is preserved in the reset-recovery folder; do not remove it. Restart the app after inspecting recovery.");
    throw error;
  }
}

export async function confirmLocalReset(options: {
  assertIdle(): Promise<void>; confirm(): Promise<boolean>; reset(): Promise<void>;
}): Promise<{ canceled: boolean }> {
  await options.assertIdle();
  if (!await options.confirm()) return { canceled: true };
  await options.assertIdle(); // Work may have changed while the native dialog was open.
  await options.reset();
  return { canceled: false };
}
