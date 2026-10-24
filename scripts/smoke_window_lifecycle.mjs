// Real Electron window destruction regression, with deterministic prompt choices.
import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
const folder = await fs.mkdtemp(path.join(os.tmpdir(), "lab-window-lifecycle-"));
const module = path.resolve("apps/desktop/dist-electron/window-lifecycle.js");
await fs.writeFile(path.join(folder, "package.json"), JSON.stringify({ main: "main.cjs" }));
await fs.writeFile(path.join(folder, "main.cjs"), `
const { app, BrowserWindow } = require('electron');
const { attachWindowLifecycle } = require(${JSON.stringify(module)});
app.disableHardwareAcceleration();
app.setPath('userData', ${JSON.stringify(path.join(folder, "profile"))});
app.whenReady().then(() => {
 const window = new BrowserWindow({ show: true, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
 let quitting = false, choice = 0, cleaned = false;
 const senderId = window.webContents.id;
 attachWindowLifecycle(window, {
  quitting: () => quitting, hasTray: () => true,
  choose: async () => ({ response: [1, 2, 0][choice++], checkboxChecked: false }),
  quit: async () => { quitting = true; window.close(); },
  closed: id => { if (id !== senderId) throw Error('Sender mismatch'); cleaned = true; console.log('REAL_WINDOW_CLOSE_PASSED'); app.quit(); },
  error: error => { console.error(error); app.exit(1); }
 });
 window.loadURL('data:text/html,<title>Lifecycle regression</title>');
 setTimeout(() => {
  window.close();
  setTimeout(() => {
   if (window.isVisible()) throw Error('Minimize did not hide');
   window.show(); window.close();
   setTimeout(() => {
    if (!window.isVisible()) throw Error('Cancel hid the window');
    window.close();
   }, 100);
  }, 100);
 }, 400);
 setTimeout(() => { if (!cleaned) app.exit(2); }, 5000).unref();
});
`);
const child = spawn(path.resolve("apps/desktop/node_modules/electron/dist/electron"), ["--ozone-platform=x11", folder], { env: { ...process.env, XDG_CONFIG_HOME: path.join(folder, "config"), XDG_CACHE_HOME: path.join(folder, "cache") }, stdio: ["ignore", "pipe", "pipe"] });
let output = "";
child.stdout.on("data", data => { output += data; });
child.stderr.on("data", data => { output += data; });
const timer = setTimeout(() => child.kill("SIGKILL"), 12_000);
const code = await new Promise((resolve, reject) => { child.once("error", reject); child.once("exit", resolve); });
clearTimeout(timer);
if (code !== 0 || !output.includes("REAL_WINDOW_CLOSE_PASSED") || output.includes("Object has been destroyed")) throw new Error(output.slice(-3000));
console.log("Real Electron: minimize, cancel, quit and destroyed-window cleanup passed (sandbox enabled).");
await fs.rm(folder, { recursive: true, force: true });
