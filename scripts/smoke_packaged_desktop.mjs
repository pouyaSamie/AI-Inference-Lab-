// Packaged-renderer smoke test; uses DISPLAY or a headless Ozone attempt. Keeps Chromium's sandbox enabled.
// The debugging socket exists only in this isolated test invocation.
import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";

const executable = path.resolve(process.argv[2] ?? "apps/desktop/release/linux-deb/opt/ai-inference-lab/desktop/ai-inference-lab-desktop");
const profile = await fs.mkdtemp(path.join(os.tmpdir(), "lab-packaged-smoke-"));
const data = path.join(profile, "config/AI Inference Optimization Lab/local-lab");
await fs.mkdir(data, { recursive: true, mode: 0o700 });
// This acceptance smoke stays offline; release networking is covered separately.
await fs.writeFile(path.join(data, "engine-update-preferences.json"), JSON.stringify({ enabled: false }), { mode: 0o600 });
if (process.env.LAB_SMOKE_MODEL_ROOT) {
  await fs.writeFile(path.join(data, "config.json"), JSON.stringify({ model_roots: [process.env.LAB_SMOKE_MODEL_ROOT], engine_roots: process.env.LAB_SMOKE_ENGINE_ROOT ? [process.env.LAB_SMOKE_ENGINE_ROOT] : [] }), { mode: 0o600 });
}
const display = process.env.DISPLAY;
const child = spawn(executable, [display ? "--ozone-platform=x11" : "--ozone-platform=headless", "--remote-debugging-port=0"], {
  cwd: profile,
  env: { PATH: "/usr/bin:/bin", HOME: profile, LANG: "C.UTF-8", ...(display ? { DISPLAY: display, XAUTHORITY: process.env.XAUTHORITY } : {}), ...(process.env.XDG_RUNTIME_DIR ? { XDG_RUNTIME_DIR: process.env.XDG_RUNTIME_DIR } : {}), XDG_CONFIG_HOME: path.join(profile, "config"), XDG_CACHE_HOME: path.join(profile, "cache") },
  stdio: ["ignore", "ignore", "pipe"],
});
let output = "";
let socket;
const pending = new Map();
let sequence = 0;
child.stderr.on("data", (data) => { output = (output + data.toString()).slice(-32_000); });
const deadline = Date.now() + 30_000;
function command(method, params = {}) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
try {
  child.on("error", (error) => { output = error.message; });
  let target;
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) throw new Error(`Electron exited (${child.exitCode ?? child.signalCode}): ${output.slice(-2000)}`);
    const endpoint = output.match(/DevTools listening on (ws:\/\/127\.0\.0\.1:\d+)\//)?.[1];
    if (endpoint) {
      try {
        const targets = await (await fetch(endpoint.replace("ws:", "http:") + "/json/list")).json();
        target = targets.find((item) => item.url.startsWith("lab://app/"));
        if (target) break;
      } catch { /* The announcement can precede the listening socket. */ }
    }
    await delay(150);
  }
  if (!target) throw new Error(`Packaged renderer did not load: ${output.slice(-2000)}`);
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message));
    else request.resolve(message.result);
  });
  let value;
  while (Date.now() < deadline) {
    let result;
    try { result = await command("Runtime.evaluate", {
      expression: "(async () => ({ title: document.title, node: typeof require, visible: document.visibilityState, runtime: await window.labDesktop.runtime.status(), info: await window.labDesktop.appInfo(), text: document.body.innerText }))()",
      returnByValue: true, awaitPromise: true,
    }); } catch (error) {
      // The target URL can appear before Chromium creates its first context.
      // Retry only this bounded startup race; bridge/application errors fail.
      if (!/Cannot find default execution context|Execution context was destroyed/.test(String(error))) throw error;
      await delay(150);
      continue;
    }
    if (result.exceptionDetails) throw new Error("Packaged renderer bridge failed");
    value = result.result.value;
    if (["needs_configuration", "error"].includes(value.runtime?.state)) break;
    await delay(150);
  }
  if (value?.visible !== "visible" || value?.node !== "undefined" || value?.runtime?.state !== "needs_configuration" || !(value.text.includes("Local lab") || value.text.includes("Set up your local lab")) || !value.info.packaged) throw new Error(`Unexpected packaged state: ${JSON.stringify(value)}`);
  // Allow the renderer's status poll and controller shell refresh to settle.
  await delay(1200);
  const ui = await command("Runtime.evaluate", { expression: "document.body.innerText", returnByValue: true });
  if (!(ui.result.value.includes("Setup in progress") || ui.result.value.includes("Needs attention")) || ui.result.value.includes("Request failed")) throw new Error("Packaged setup UI did not settle into a healthy configuration state");
  if (process.argv[3]) {
    const screenshot = await command("Page.captureScreenshot", { format: "png" });
    await fs.writeFile(path.resolve(process.argv[3]), Buffer.from(screenshot.data, "base64"));
  }
  const alignment = await command("Runtime.evaluate", { returnByValue: true, expression: "JSON.stringify({ overflow: document.documentElement.scrollWidth > innerWidth, tops: [...document.querySelectorAll('.grid-2')].map(grid => [...grid.children].filter(el => el.classList.contains('panel')).map(el => el.getBoundingClientRect().top)) })" });
  const layout = JSON.parse(alignment.result.value);
  if (layout.overflow || layout.tops.some(row => row.length === 2 && Math.abs(row[0] - row[1]) > 1)) throw new Error("Overview columns are misaligned or overflow the viewport");
  if (process.env.LAB_SMOKE_RESET_UI === "1") {
    await command("Runtime.evaluate", { expression: "location.hash = '#/settings'" });
    await delay(1000);
    const resetUi = await command("Runtime.evaluate", { returnByValue: true, expression: "({ bridge: typeof window.labDesktop.runtime.resetData, available: [...document.querySelectorAll('button')].some(b => b.textContent === 'Reset local data…' && !b.disabled), text: document.body.innerText.includes('Model files and installed engine builds are kept') })" });
    if (resetUi.result.value.bridge !== "function" || !resetUi.result.value.available || !resetUi.result.value.text) throw new Error("Packaged reset UI/bridge unavailable for the idle managed profile");
    await command("Runtime.evaluate", { expression: "[...document.querySelectorAll('h2')].find(h => h.textContent === 'Start fresh').closest('section').scrollIntoView({block:'center'})" });
    if (process.argv[3]) {
      const shot = await command("Page.captureScreenshot", { format: "png" });
      await fs.writeFile(path.resolve(process.argv[3]).replace(/\.png$/, "-settings.png"), Buffer.from(shot.data, "base64"));
    }
    console.log("Packaged Settings reset UI and isolated bridge passed; no reset invoked.");
  }
  if (process.env.LAB_SMOKE_MODEL_ROOT) {
    if (!(value.runtime.inventory?.models > 0) || !(value.runtime.engine_candidates?.length > 0)) throw new Error("Folder discovery did not populate model/build inventory");
    const evaluate = (expression) => command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    await evaluate("[...document.querySelectorAll('.setup-navigation button')].find(b => b.textContent === 'Continue').click()");
    await delay(200);
    if (process.argv[3]) {
      const screenshot = await command("Page.captureScreenshot", { format: "png" });
      await fs.writeFile(path.resolve(process.argv[3]).replace(/\.png$/, "-engines.png"), Buffer.from(screenshot.data, "base64"));
    }
    await evaluate("[...document.querySelectorAll('.setup-navigation button')].find(b => b.textContent === 'Continue').click()");
    await delay(100);
    await evaluate("[...document.querySelectorAll('.setup-navigation button')].find(b => b.textContent === 'Save setup').click()");
    await command("Page.reload");
    await delay(1800);
    const saved = await evaluate("document.body.innerText.includes('Edit setup') && localStorage.getItem('lab.setup.complete') === '1'");
    if (saved.result.value !== true) throw new Error("Completed wizard did not persist across reload");
    await evaluate("location.hash = '#/models'");
    await delay(1800);
    const models = await evaluate("document.body.innerText");
    if (!models.result.value.includes("Discovered models") || models.result.value.includes("Request failed")) throw new Error("Models page did not show the cached discovered inventory");
    if (process.argv[3]) {
      const screenshot = await command("Page.captureScreenshot", { format: "png" });
      await fs.writeFile(path.resolve(process.argv[3]).replace(/\.png$/, "-models.png"), Buffer.from(screenshot.data, "base64"));
    }
    console.log(`Wizard save/reload and model browsing passed: ${value.runtime.inventory.models} models, ${value.runtime.engine_candidates.length} build locations (no engine selected)`);
  }
  console.log(JSON.stringify({ title: value.title, version: value.info.version, packaged: value.info.packaged, renderer_node: value.node, visible: value.visible, runtime: value.runtime.state, sandbox: value.info.security.sandbox }));
} finally {
  await fs.writeFile(path.join(profile, "electron-stderr.log"), output);
  socket?.close();
  child.kill("SIGTERM");
  await Promise.race([new Promise((resolve) => child.once("exit", resolve)), delay(3000)]);
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
  // Give the parent-EOF supervisor time to stop the optimizer and controller.
  await delay(2000);
  // Leave failed-test profile evidence available for diagnosis; no real data
  // or engines are ever configured in this profile.
  console.log(`Temporary smoke profile: ${profile}`);
}
