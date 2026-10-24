import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, it } from "vitest";
import { DesktopDiagnostics } from "./desktop-diagnostics";

it("rotates bounded private diagnostics and omits unapproved fields", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "lab-diagnostics-"));
  try {
    const file = path.join(directory, "desktop-events.log");
    await fs.writeFile(file, "x".repeat(256 * 1024));
    const log = new DesktopDiagnostics(directory);
    const event = { operation: "folder-picker" as const, request_id: "test-id", stage: "opened" as const, kind: "model_roots", token: "must-not-be-logged", path: "/private/model" };
    await Promise.all([log.record(event), log.record({ ...event, stage: "cancelled" })]);
    const lines = (await fs.readFile(file, "utf8")).trim().split("\n");
    expect(lines.map(line => JSON.parse(line).stage)).toEqual(["opened", "cancelled"]);
    expect(lines.join("\n")).not.toContain("must-not-be-logged");
    expect(lines.join("\n")).not.toContain("/private/model");
    expect((await fs.stat(`${file}.1`)).size).toBe(256 * 1024);
    expect((await fs.stat(file)).mode & 0o777).toBe(0o600);
  } finally { await fs.rm(directory, { recursive: true, force: true }); }
});
