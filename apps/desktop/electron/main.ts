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
  type IpcMainInvokeEvent,
  type SaveDialogOptions,
} from "electron";
import { promises as fs } from "node:fs";
import path from "node:path";
import { ApiProxy } from "./api-proxy";
import {
  IPC,
  isTrustedFrameUrl,
  validateReportContent,
  validateReportName,
} from "./security";
import { SettingsStore } from "./settings";
import { SseBridge } from "./sse-bridge";

// The desktop UI is an operator console; GPU acceleration is not needed for it.
// This must run before the app becomes ready. An explicit environment override
// exists for operators, but shared-GPU qualification then requires contamination
// verification outside this UI.
const GPU_ACCELERATION_ENABLED = process.env.LAB_DESKTOP_ENABLE_GPU === "1";
if (!GPU_ACCELERATION_ENABLED) app.disableHardwareAcceleration();

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
  if (!DEV_CANDIDATE) return null;
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
  // normal close path still exits the UI; jobs remain controller-owned either
  // way. Closing the window only hides it when a tray exists.
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
          label: "Quit UI (jobs keep running)",
          click: () => {
            quitting = true;
            app.quit();
          },
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
    show: false,
    backgroundColor: "#0d1117",
    autoHideMenuBar: true,
    title: "AI Inference Optimization Lab",
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

  window.once("ready-to-show", () => window.show());
  window.on("close", (event) => {
    if (tray && !quitting) {
      event.preventDefault();
      window.hide();
    }
  });
  window.on("closed", () => {
    events?.closeForSender(window.webContents.id);
    if (mainWindow === window) mainWindow = null;
  });

  if (DEV_ORIGIN) {
    void window.loadURL(DEV_ORIGIN);
  } else {
    void window.loadURL("lab://app/index.html");
  }
  return window;
}

function registerIpc(): void {
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
        token_storage: settings?.status().secure_storage_available ? "safeStorage" : "session memory",
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

app.whenReady().then(async () => {
  app.setAppUserModelId("lab.inference.optimizer");
  settings = new SettingsStore(app.getPath("userData"));
  await settings.load();
  proxy = new ApiProxy(settings);
  events = new SseBridge(settings);

  protocol.handle("lab", serveRenderer);
  configureSession();
  registerIpc();
  mainWindow = createWindow();
  createTray();

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

app.on("before-quit", () => {
  quitting = true;
  events?.shutdown();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
