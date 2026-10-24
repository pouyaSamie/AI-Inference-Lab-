import { confirmLocalReset, resetManagedData } from "./reset-data";
import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  nativeImage,
  protocol,
  session,
  Tray,
  shell,
  type IpcMainInvokeEvent,
  type SaveDialogOptions,
} from "electron";
import { promises as fs } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { DesktopDiagnostics } from "./desktop-diagnostics";
import { EngineUpdates, removableBuild } from "./engine-updates";
import { attachWindowLifecycle } from "./window-lifecycle";
import { ApiProxy } from "./api-proxy";
import {
  IPC,
  isTrustedFrameUrl,
  validateReportContent,
  validateReportName,
} from "./security";
import { SettingsStore } from "./settings";
import { SseBridge } from "./sse-bridge";
import { RuntimeManager, PATH_KINDS, type PathKind } from "./runtime-manager";

// The desktop UI is an operator console; GPU acceleration is not needed for it.
// This must run before the app becomes ready. An explicit environment override
// exists for operators, but shared-GPU qualification then requires contamination
// verification outside this UI.
const GPU_ACCELERATION_ENABLED = process.env.LAB_DESKTOP_ENABLE_GPU === "1";
if (!GPU_ACCELERATION_ENABLED) app.disableHardwareAcceleration();
if (process.platform === "linux") {
  app.commandLine.appendSwitch("class", "ai-inference-lab");
  app.setDesktopName("ai-inference-lab.desktop");
}

protocol.registerSchemesAsPrivileged([
  {
    scheme: "lab",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: false,
      stream: true,
    },
  },
]);

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

const DIST = path.resolve(__dirname, "..", "dist");
const DEV_CANDIDATE = process.env.LAB_DESKTOP_DEV_SERVER?.trim() ?? "";
const DEV_ORIGIN = (() => {
  if (app.isPackaged || !DEV_CANDIDATE) return null;
  try {
    const url = new URL(DEV_CANDIDATE);
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)) return null;
    return url.origin;
  } catch {
    return null;
  }
})();

const PRODUCTION_CSP = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  "connect-src 'none'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
].join("; ");

const DEV_CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  "connect-src 'self' ws://127.0.0.1:* http://127.0.0.1:* ws://localhost:* http://localhost:*",
  "object-src 'none'",
  "base-uri 'none'",
  "frame-ancestors 'none'",
].join("; ");

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".map": "application/json; charset=utf-8",
};

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let settings: SettingsStore | null = null;
let proxy: ApiProxy | null = null;
let events: SseBridge | null = null;
let quitting = false;
let quitPending = false;
let selectingRuntimePath = false;
let runtime: RuntimeManager | null = null;
let engineUpdates: EngineUpdates | null = null;
let engineOperation: Promise<unknown> | null = null;
let desktopDiagnostics: DesktopDiagnostics | null = null;

function hasActiveLocalWork(value: unknown): boolean {
  const status = value as { experiments_active?: number; serving_active?: number } | null;
  return status?.experiments_active !== 0 || (status?.serving_active ?? 0) !== 0;
}

async function requestQuit(confirmed = false): Promise<void> {
  if (quitPending || quitting) return;
  quitPending = true;
  try {
    if (runtime) {
      if (!confirmed) {
        const answer = await dialog.showMessageBox({ type: "question", title: "Quit Inference Lab?", message: "Quit and stop the local lab?", detail: "Active work will be interrupted safely.", buttons: ["Keep running", "Stop and quit"], defaultId: 0, cancelId: 0 });
        if (answer.response !== 1) return;
      }
      engineUpdates?.cancel();
      await engineOperation?.catch(() => undefined);
      events?.shutdown();
      await runtime.stop();
    }
    quitting = true;
    app.quit();
  } catch (error) {
    dialog.showErrorBox("Could not stop the local lab", error instanceof Error ? error.message : "Wait for shutdown, then try again.");
  } finally { quitPending = false; }
}

function assertTrusted(event: IpcMainInvokeEvent): void {
  const frameUrl = event.senderFrame?.url ?? "";
  if (!isTrustedFrameUrl(frameUrl, DEV_ORIGIN)) {
    throw new Error("Untrusted renderer frame");
  }
}

async function serveRenderer(request: Request): Promise<Response> {
  const url = new URL(request.url);
  if (url.host !== "app") return new Response("Not found", { status: 404 });
  let pathname: string;
  try {
    pathname = decodeURIComponent(url.pathname);
  } catch {
    return new Response("Bad request", { status: 400 });
  }
  if (pathname === "/" || pathname === "") pathname = "/index.html";
  if (pathname.includes("\u0000") || pathname.includes("\\")) {
    return new Response("Bad request", { status: 400 });
  }
  const resolved = path.resolve(DIST, `.${pathname}`);
  if (!resolved.startsWith(`${DIST}${path.sep}`)) {
    return new Response("Not found", { status: 404 });
  }
  try {
    const data = await fs.readFile(resolved);
    const extension = path.extname(resolved).toLowerCase();
    return new Response(new Uint8Array(data), {
      status: 200,
      headers: {
        "Content-Type": MIME[extension] ?? "application/octet-stream",
        "Content-Security-Policy": PRODUCTION_CSP,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), usb=(), serial=(), hid=()",
      },
    });
  } catch {
    return new Response("Not found", { status: 404 });
  }
}

function configureSession(): void {
  const defaultSession = session.defaultSession;
  defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  defaultSession.setPermissionCheckHandler(() => false);
  defaultSession.setDevicePermissionHandler(() => false);
  defaultSession.setDisplayMediaRequestHandler((_request, callback) => {
    callback({});
  });

  defaultSession.webRequest.onHeadersReceived((details, callback) => {
    if (DEV_ORIGIN && details.url.startsWith(DEV_ORIGIN)) {
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          "Content-Security-Policy": [DEV_CSP],
          "X-Content-Type-Options": ["nosniff"],
          "Referrer-Policy": ["no-referrer"],
        },
      });
    } else {
      callback({});
    }
  });
}

function hardenContents(contents: Electron.WebContents): void {
  contents.setWindowOpenHandler(() => ({ action: "deny" }));
  contents.on("will-attach-webview", (event) => event.preventDefault());
  contents.on("will-navigate", (event, url) => {
    if (!isTrustedFrameUrl(url, DEV_ORIGIN)) event.preventDefault();
  });
  contents.on("will-redirect", (event, url) => {
    if (!isTrustedFrameUrl(url, DEV_ORIGIN)) event.preventDefault();
  });
  contents.on("before-input-event", (event, input) => {
    if (app.isPackaged && (input.key === "F12" || (input.control && input.shift && input.key.toLowerCase() === "i"))) {
      event.preventDefault();
    }
  });
}

function showMainWindow(): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    mainWindow = createWindow();
    return;
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function createTray(): void {
  // A tray is optional on minimal Linux desktops. If it cannot be created the
  // close prompt offers a taskbar minimize fallback when a tray is unavailable.
  try {
    const iconPath = app.isPackaged
      ? path.join(DIST, "tray.png")
      : path.join(__dirname, "..", "public", "tray.png");
    const icon = nativeImage.createFromPath(iconPath);
    if (icon.isEmpty()) return;
    tray = new Tray(icon.resize({ width: 16, height: 16 }));
    tray.setToolTip("AI Inference Optimization Lab — jobs keep running when this window is hidden");
    tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: "Show operator console", click: () => showMainWindow() },
        { type: "separator" },
        {
          label: "Quit",
          click: () => { void requestQuit(); },
        },
      ]),
    );
    tray.on("click", () => showMainWindow());
  } catch (error) {
    console.warn(
      "System tray is unavailable; closing the window will exit the UI",
      error instanceof Error ? error.message : "unknown error",
    );
    tray = null;
  }
}

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1460,
    height: 960,
    minWidth: 1024,
    minHeight: 700,
    // Show the shell immediately; startup visibility must not depend on the
    // renderer reaching ready-to-show on every Linux window manager.
    show: true,
    backgroundColor: "#0d1117",
    autoHideMenuBar: true,
    title: "AI Inference Optimization Lab",
    icon: path.join(DIST, "app-icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      nodeIntegrationInSubFrames: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      experimentalFeatures: false,
      spellcheck: false,
      devTools: !app.isPackaged,
    },
  });

  attachWindowLifecycle(window, {
    quitting: () => quitting,
    hasTray: () => !!tray,
    choose: (options) => dialog.showMessageBox(window, options),
    quit: () => requestQuit(true),
    closed: (senderId) => { events?.closeForSender(senderId); if (mainWindow === window) mainWindow = null; },
    error: (error) => dialog.showErrorBox("Could not close the window", error instanceof Error ? error.message : "Please try again."),
  });

  if (DEV_ORIGIN) {
    void window.loadURL(DEV_ORIGIN);
  } else {
    void window.loadURL("lab://app/index.html");
  }
  return window;
}

function registerIpc(): void {
  ipcMain.handle(IPC.updatesStatus, event => { assertTrusted(event); return engineUpdates?.status() ?? null; });
  ipcMain.handle(IPC.updatesCheck, async event => { assertTrusted(event); if (!engineUpdates) throw new Error("Managed runtime required"); return engineUpdates.check(); });
  ipcMain.handle(IPC.updatesPreference, async (event, enabled: unknown) => { assertTrusted(event); if (!engineUpdates || typeof enabled !== "boolean") throw new Error("Invalid preference"); return engineUpdates.setEnabled(enabled); });
  const engineAction = async (event: IpcMainInvokeEvent, run: () => Promise<{ canceled: boolean }>) => {
    assertTrusted(event);
    if (!runtime || !engineUpdates || selectingRuntimePath || quitPending || !["ready", "needs_configuration"].includes(runtime.status().state)) throw new Error("Wait for the current runtime operation to finish");
    selectingRuntimePath = true;
    try {
      const response = await proxy?.request("GET", "/api/v1/status", undefined, null);
      if (!response?.ok || hasActiveLocalWork(response.body)) throw new Error("Stop the recipe engine and finish or cancel active jobs before changing engines");
      if (quitPending) throw new Error("Shutdown is in progress");
      const task = run(); engineOperation = task;
      return await task;
    } catch (error) { engineUpdates?.reportFailure(error); throw error; }
    finally { engineOperation = null; selectingRuntimePath = false; }
  };
  ipcMain.handle(IPC.updatesInstall, (event, family: unknown, assetId: unknown) => engineAction(event, async () => {
    if (process.platform !== "linux" || !Number.isSafeInteger(assetId)) throw new Error("Choose a supported Linux asset");
    const { release, asset } = engineUpdates!.asset(family, assetId);
    const answer = await dialog.showMessageBox({ type: "question", title: "Install engine update?", message: `Install ${release.engine_id === "llamacpp" ? "llama.cpp" : "Strata"} ${release.version}?`, detail: `${asset.name}\nDownload: ${Math.ceil((asset.size + (release.support?.size ?? 0) + (release.dependencies?.[asset.id] ?? []).reduce((sum, item) => sum + item.size, 0)) / 1024 ** 2)} MiB from the official project. Archive SHA-256 is verified. Existing builds are kept. Choose the installed build after discovery; compatibility and benchmarks still need verification.`, buttons: ["Cancel", "Install update"], defaultId: 0, cancelId: 0 });
    if (answer.response !== 1 || quitPending) return { canceled: true };
    try {
      const managed = await engineUpdates!.install(family, assetId);
      if (!quitPending) {
        events?.shutdown(); await runtime!.stop();
        await runtime!.select("engine_roots", managed);
      }
    } finally { if (!quitPending) await runtime!.start(); }
    return { canceled: false };
  }));
  ipcMain.handle(IPC.engineRemove, (event, id: unknown) => engineAction(event, async () => {
    if (typeof id !== "string" || !/^[a-f0-9]{24}$/.test(id)) throw new Error("Invalid build selection");
    const build = runtime!.status().engine_candidates?.find(b => b.id === id);
    if (!build) throw new Error("Rescan and choose a discovered build");
    const directory = await removableBuild(build, runtime!.status(), path.join(app.getPath("userData"), "local-lab/managed-engines"));
    const answer = await dialog.showMessageBox({ type: "warning", title: "Remove old engine build?", message: `Move ${build.label} to Trash?`, detail: `${directory}\nOnly this isolated build directory is removed. Selected/shared engines and model folders are protected.`, buttons: ["Keep build", "Move to Trash"], defaultId: 0, cancelId: 0 });
    if (answer.response !== 1 || quitPending) return { canceled: true };
    events?.shutdown(); await runtime!.stop();
    try {
      const rechecked = await removableBuild(build, runtime!.status(), path.join(app.getPath("userData"), "local-lab/managed-engines"));
      if (rechecked !== directory) throw new Error("Build location changed; rescan first");
      await shell.trashItem(directory);
    } finally { if (!quitPending) await runtime!.start(); }
    return { canceled: false };
  }));

  ipcMain.handle(IPC.runtimeReset, async event => {
    assertTrusted(event);
    if (!runtime || !settings || !["ready", "needs_configuration"].includes(runtime.status().state)) throw new Error("Reset requires a healthy local lab. Retry startup first.");
    if (selectingRuntimePath || quitPending || engineOperation || engineUpdates?.status().operation) throw new Error("Wait for the current local operation to finish");
    const localRuntime = runtime;
    selectingRuntimePath = true;
    try {
      const assertIdle = async () => {
        const response = await proxy?.request("GET", "/api/v1/status", undefined, null);
        if (!response?.ok || hasActiveLocalWork(response.body)) throw new Error("Finish or cancel active jobs and stop the recipe engine before resetting local data");
      };
      const owner = BrowserWindow.fromWebContents(event.sender);
      if (!owner) throw new Error("Reset requires an active application window");
      const outcome = await confirmLocalReset({
        assertIdle,
        confirm: async () => {
          const answer = await dialog.showMessageBox(owner, {
            type: "warning", title: "Start fresh?", message: "Remove all local lab records and restart?",
            detail: "Studies, recipes, cached inventory, verification, saved folders, preferences and credentials will be reset. Model files and installed engine builds are kept. Lab records are moved to the system Trash for recovery; this is not a secure erase. Export anything you need first.",
            buttons: ["Cancel", "Reset local data and restart"], defaultId: 0, cancelId: 0, noLink: true,
          });
          return answer.response === 1;
        },
        reset: async () => {
          if (quitPending) throw new Error("Shutdown is in progress");
          const config = localRuntime.status().config;
          const protectedPaths = Object.values(config).flatMap(value => Array.isArray(value) ? value : typeof value === "string" ? [value] : []);
          engineUpdates?.cancel(); await engineOperation;
          events?.shutdown();
          await resetManagedData({
            userData: app.getPath("userData"), protectedPaths,
            stop: () => localRuntime.stop(),
            clearBrowserData: async () => { await session.defaultSession.clearStorageData(); await session.defaultSession.clearCache(); },
            trash: folder => shell.trashItem(folder),
          });
        },
      });
      if (outcome.canceled) return outcome;
      quitting = true;
      app.relaunch();
      setTimeout(() => app.exit(0), 250);
      return { canceled: false };
    } finally { if (!quitting) selectingRuntimePath = false; }
  });

  ipcMain.handle(IPC.runtimeStatus, (event) => { assertTrusted(event); return runtime?.status() ?? null; });
  ipcMain.handle(IPC.runtimeRetry, async (event) => {
    assertTrusted(event);
    if (!runtime) throw new Error("No managed runtime");
    if (runtime.status().state === "starting" || selectingRuntimePath || quitPending) throw new Error("Wait for the current operation to finish");
    selectingRuntimePath = true;
    try {
      if (["ready", "needs_configuration"].includes(runtime.status().state)) {
        const response = await proxy?.request("GET", "/api/v1/status", undefined, null);
        if (!response?.ok || hasActiveLocalWork(response.body)) throw new Error("Stop the recipe engine and finish or cancel active jobs before rescanning");
      }
      if (quitPending) throw new Error("Shutdown is in progress");
      events?.shutdown(); await runtime.retry();
    } finally { selectingRuntimePath = false; }
    return runtime.status();
  });
  ipcMain.handle(IPC.runtimeRemoveFolder, async (event, kind: unknown, index: unknown) => {
    assertTrusted(event);
    if (!runtime || !["model_roots", "engine_roots"].includes(String(kind)) || typeof index !== "number" || !Number.isInteger(index)) throw new Error("Invalid folder selection");
    if (["starting", "stopped"].includes(runtime.status().state) || selectingRuntimePath || quitPending) throw new Error("Wait for the current operation to finish");
    selectingRuntimePath = true;
    try {
      if (runtime.status().state !== "error") {
        const response = await proxy?.request("GET", "/api/v1/status", undefined, null);
        if (!response?.ok || hasActiveLocalWork(response.body)) throw new Error("Stop the recipe engine and finish or cancel active jobs before removing folders");
      }
      events?.shutdown();
      await runtime.removeFolder(kind as "model_roots" | "engine_roots", index);
    } finally { selectingRuntimePath = false; }
    return runtime.status();
  });
  ipcMain.handle(IPC.runtimeUseEngine, async (event, id: unknown) => {
    assertTrusted(event);
    if (!runtime || typeof id !== "string" || !/^[a-f0-9]{24}$/.test(id)) throw new Error("Invalid engine build");
    if (["starting", "stopped"].includes(runtime.status().state) || selectingRuntimePath || quitPending) throw new Error("Wait for startup or configuration to finish");
    selectingRuntimePath = true;
    try {
      const response = await proxy?.request("GET", "/api/v1/status", undefined, null);
      if (!response?.ok || hasActiveLocalWork(response.body)) throw new Error("Stop the recipe engine and finish or cancel active jobs before changing engines");
      if (quitPending) throw new Error("Shutdown is in progress");
      events?.shutdown(); await runtime.useEngine(id);
    } finally { selectingRuntimePath = false; }
    return runtime.status();
  });
  ipcMain.handle(IPC.runtimeSelect, async (event, kind: unknown) => {
    assertTrusted(event);
    if (!runtime || typeof kind !== "string" || !PATH_KINDS.includes(kind as PathKind)) throw new Error("Invalid configuration selection");
    if (["starting", "stopped"].includes(runtime.status().state)) throw new Error("Wait for startup to finish");
    const diagnostics = desktopDiagnostics ??= new DesktopDiagnostics(app.getPath("userData"));
    const requestId = randomUUID();
    const started = Date.now();
    const trace = (stage: "requested" | "opened" | "selected" | "cancelled" | "failed" | "busy") => diagnostics.record({ operation: "folder-picker", request_id: requestId, stage, kind, elapsed_ms: Date.now() - started });
    await trace("requested");
    if (selectingRuntimePath || quitPending) {
      await trace("busy");
      throw new Error("A folder picker or setup operation is already open. Finish or cancel it before choosing another folder.");
    }
    selectingRuntimePath = true;
    try {
      if (proxy && runtime.status().state !== "error") {
        const response = await proxy.request("GET", "/api/v1/status", undefined, null);
        if (!response.ok || hasActiveLocalWork(response.body)) throw new Error("Stop the recipe engine and finish or cancel active jobs before changing local configuration");
      }
      if (quitPending) throw new Error("Shutdown is in progress");
      const directories = ["model_roots", "engine_roots", "llama_lib_dir"].includes(kind);
      const owner = BrowserWindow.fromWebContents(event.sender);
      if (!owner || owner.isDestroyed()) throw new Error("Reopen the lab window before choosing a folder.");
      if (owner.isMinimized()) owner.restore();
      owner.show();
      owner.focus();
      await trace("opened");
      const selection = await dialog.showOpenDialog(owner, { title: `Select ${kind.replaceAll("_", " ")}`, properties: [directories ? "openDirectory" : "openFile"] });
      await trace(selection.canceled ? "cancelled" : "selected");
      if (!selection.canceled && selection.filePaths[0] && !quitPending) {
        events?.shutdown();
        await runtime.select(kind as PathKind, selection.filePaths[0]);
      }
    } catch (error) {
      await trace("failed");
      throw error;
    } finally { selectingRuntimePath = false; }
    return runtime.status();
  });

  ipcMain.handle(IPC.appInfo, (event) => {
    assertTrusted(event);
    return {
      version: app.getVersion(),
      platform: process.platform,
      packaged: app.isPackaged,
      security: {
        context_isolation: true,
        node_integration: false,
        sandbox: true,
        hardware_acceleration: GPU_ACCELERATION_ENABLED
          ? "operator override enabled; shared-GPU qualification requires contamination verification"
          : "disabled",
        navigation: "blocked",
        permissions: "denied",
        api_transport: "validated IPC proxy",
        token_storage: runtime ? "session memory" : settings?.status().secure_storage_available ? "safeStorage" : "session memory",
      },
    };
  });

  ipcMain.handle(IPC.settingsStatus, (event) => {
    assertTrusted(event);
    return settings?.status();
  });

  ipcMain.handle(IPC.settingsSetUrl, (event, raw: unknown) => {
    assertTrusted(event);
    if (typeof raw !== "string") throw new Error("API URL must be a string");
    return settings?.setApiBaseUrl(raw);
  });

  ipcMain.handle(IPC.settingsSetToken, async (event, raw: unknown) => {
    assertTrusted(event);
    if (typeof raw !== "string") throw new Error("Token must be a string");
    return settings?.setToken(raw);
  });

  ipcMain.handle(IPC.settingsClearToken, async (event) => {
    assertTrusted(event);
    return settings?.clearToken();
  });

  ipcMain.handle(
    IPC.apiRequest,
    async (event, method: unknown, apiPath: unknown, body: unknown, idempotencyKey: unknown) => {
      assertTrusted(event);
      if (!proxy) throw new Error("API proxy is not ready");
      if ((selectingRuntimePath || quitPending) && method === "POST") return { status: 409, ok: false, body: null, error: "Wait for the local runtime operation to finish" };
      if (runtime && !["ready", "needs_configuration"].includes(runtime.status().state)) return { status: 0, ok: false, body: null, error: runtime.status().message };
      return proxy.request(method, apiPath, body, idempotencyKey);
    },
  );

  ipcMain.handle(IPC.eventsSubscribe, (event, experimentId: unknown, lastEventId: unknown) => {
    assertTrusted(event);
    if (!events) throw new Error("Event bridge is not ready");
    return events.subscribe(event.sender, experimentId, lastEventId);
  });

  ipcMain.handle(IPC.eventsUnsubscribe, (event, id: unknown) => {
    assertTrusted(event);
    events?.unsubscribe(id, event.sender);
  });

  ipcMain.handle(IPC.saveReport, async (event, nameRaw: unknown, contentRaw: unknown) => {
    assertTrusted(event);
    const name = validateReportName(nameRaw);
    if (!name.ok || !name.value) throw new Error(name.reason ?? "Report filename is invalid");
    const content = validateReportContent(contentRaw);
    if (!content.ok || content.value === undefined) throw new Error(content.reason ?? "Report content is invalid");
    if (Buffer.byteLength(content.value, "utf8") > 4_194_304) throw new Error("Report content is too large");
    const extension = path.extname(name.value).replace(/^\./, "") || "json";
    const owner = BrowserWindow.fromWebContents(event.sender) ?? mainWindow;
    const options: SaveDialogOptions = {
      title: "Save operator report",
      defaultPath: path.join(app.getPath("documents"), name.value),
      filters: [{ name: "Operator report", extensions: [extension] }],
      properties: ["createDirectory", "showOverwriteConfirmation"],
    };
    const result = owner
      ? await dialog.showSaveDialog(owner, options)
      : await dialog.showSaveDialog(options);
    if (result.canceled || !result.filePath) return { canceled: true };
    await fs.writeFile(result.filePath, content.value, { encoding: "utf8", mode: 0o600 });
    await fs.chmod(result.filePath, 0o600).catch(() => undefined);
    return { canceled: false, path: result.filePath };
  });
}

app.on("web-contents-created", (_event, contents) => hardenContents(contents));

app.on("second-instance", () => showMainWindow());

if (gotLock) app.whenReady().then(async () => {
  app.setAppUserModelId("lab.inference.optimizer");
  const managed = app.isPackaged || process.env.LAB_DESKTOP_MANAGED === "1";
  settings = new SettingsStore(app.getPath("userData"), managed);
  await settings.load();
  proxy = new ApiProxy(settings);
  events = new SseBridge(settings);

  protocol.handle("lab", serveRenderer);
  configureSession();
  registerIpc();
  mainWindow = createWindow();
  createTray();
  showMainWindow();
  if (managed) {
    runtime = new RuntimeManager(path.join(__dirname, "..", "backend"), path.join(app.getPath("userData"), "local-lab"), settings);
    engineUpdates = new EngineUpdates(path.join(app.getPath("userData"), "local-lab"), path.join(__dirname, "..", "backend"), () => runtime!.status());
    const updatePreferences = engineUpdates.load();
    void runtime.start();
    await updatePreferences;
    let attempts = 0;
    const startupCheck = setInterval(() => {
      if (quitting || ++attempts > 90) { clearInterval(startupCheck); return; }
      if (runtime && ["ready", "needs_configuration"].includes(runtime.status().state)) {
        clearInterval(startupCheck);
        if (engineUpdates?.status().enabled) void engineUpdates.check();
      }
    }, 1000);
    startupCheck.unref();
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      mainWindow = createWindow();
    } else {
      showMainWindow();
    }
  });
}).catch((error: unknown) => {
  console.error("Failed to start desktop shell", error instanceof Error ? error.message : "unknown error");
  app.quit();
});

app.on("before-quit", (event) => {
  if (runtime && !quitting) { event.preventDefault(); void requestQuit(); return; }
  quitting = true;
  events?.shutdown();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
