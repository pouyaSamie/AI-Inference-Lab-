import { spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const run = (command, args) => {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit", env: process.env });
  if (result.status !== 0) process.exit(result.status ?? 1);
};

run(process.execPath, [resolve(root, "node_modules/vite/bin/vite.js"), "build"]);
run(process.execPath, [resolve(root, "node_modules/typescript/bin/tsc"), "-p", "tsconfig.electron.json"]);
mkdirSync(resolve(root, "dist-electron"), { recursive: true });
writeFileSync(
  resolve(root, "dist-electron/package.json"),
  `${JSON.stringify({ type: "commonjs" }, null, 2)}\n`,
  "utf8",
);
console.log("Built renderer and Electron entrypoints.");
