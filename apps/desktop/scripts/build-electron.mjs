import { spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const result = spawnSync(
  process.execPath,
  [resolve(root, "node_modules/typescript/bin/tsc"), "-p", "tsconfig.electron.json"],
  { cwd: root, stdio: "inherit", env: process.env },
);
if (result.status !== 0) process.exit(result.status ?? 1);
mkdirSync(resolve(root, "dist-electron"), { recursive: true });
writeFileSync(
  resolve(root, "dist-electron/package.json"),
  `${JSON.stringify({ type: "commonjs" }, null, 2)}\n`,
  "utf8",
);
console.log("Built Electron main and preload.");
