import { spawn } from "node:child_process";
import { connect } from "node:net";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const host = "127.0.0.1";
const port = 5173;
const devUrl = `http://${host}:${port}`;

const vite = spawn(
  process.execPath,
  [resolve(root, "node_modules/vite/bin/vite.js"), "--host", host, "--port", String(port), "--strictPort"],
  { cwd: root, stdio: "inherit", env: { ...process.env } },
);

let electron = null;
let stopped = false;

function shutdown(code = 0) {
  if (stopped) return;
  stopped = true;
  electron?.kill("SIGTERM");
  vite.kill("SIGTERM");
  setTimeout(() => process.exit(code), 150);
}

function waitForPort(attempt = 0) {
  if (stopped) return;
  const socket = connect({ host, port });
  socket.once("connect", () => {
    socket.destroy();
    const binary = resolve(root, "node_modules/.bin/electron");
    electron = spawn(binary, ["."], {
      cwd: root,
      stdio: "inherit",
      env: { ...process.env, LAB_DESKTOP_DEV_SERVER: devUrl, ELECTRON_ENABLE_LOGGING: "1" },
    });
    electron.once("exit", (code) => shutdown(code ?? 0));
  });
  socket.once("error", () => {
    socket.destroy();
    if (attempt > 80) {
      console.error("Vite did not become ready in time.");
      shutdown(1);
      return;
    }
    setTimeout(() => waitForPort(attempt + 1), 250);
  });
}

vite.once("exit", (code) => {
  if (!stopped) {
    console.error(`Vite exited with code ${code ?? "unknown"}`);
    shutdown(code ?? 1);
  }
});

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
waitForPort();
