import { promises as fs } from "node:fs";
import path from "node:path";

export interface DesktopDiagnostic {
  operation: "folder-picker";
  request_id: string;
  stage: "requested" | "opened" | "selected" | "cancelled" | "failed" | "busy";
  kind: string;
  elapsed_ms?: number;
}

// Deliberately excludes paths, error messages, process arguments and secrets.
// Serialized writes bound storage to two 256 KiB files per application profile.
export class DesktopDiagnostics {
  private pending: Promise<void> = Promise.resolve();
  constructor(private readonly directory: string) {}

  record(event: DesktopDiagnostic): Promise<void> {
    this.pending = this.pending.then(async () => {
      await fs.mkdir(this.directory, { recursive: true, mode: 0o700 });
      const file = path.join(this.directory, "desktop-events.log");
      const size = await fs.stat(file).then(stat => stat.size).catch(() => 0);
      if (size >= 256 * 1024) await fs.rename(file, `${file}.1`);
      const entry = { at: new Date().toISOString(), operation: event.operation, request_id: event.request_id.slice(0, 64), stage: event.stage, kind: event.kind.slice(0, 64), elapsed_ms: event.elapsed_ms };
      await fs.appendFile(file, JSON.stringify(entry) + "\n", { mode: 0o600 });
      await fs.chmod(file, 0o600);
    }).catch(() => { /* Diagnostics must not prevent selection or shutdown. */ });
    return this.pending;
  }
}
