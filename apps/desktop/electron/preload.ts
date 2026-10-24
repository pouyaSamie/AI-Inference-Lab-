import { contextBridge, ipcRenderer } from "electron";

// Sandboxed preload scripts cannot require local modules. Keep this channel list
// in lockstep with electron/security.ts; main-process validation is authoritative.
const IPC = {
  updatesStatus: "lab:engines:updates-status",
  updatesCheck: "lab:engines:updates-check",
  updatesPreference: "lab:engines:updates-preference",
  updatesInstall: "lab:engines:updates-install",
  engineRemove: "lab:engines:remove",
  runtimeStatus: "lab:runtime:status",
  runtimeReset: "lab:runtime:reset-data",
  runtimeRetry: "lab:runtime:retry",
  runtimeSelect: "lab:runtime:select",
  runtimeUseEngine: "lab:runtime:use-engine",
  runtimeRemoveFolder: "lab:runtime:remove-folder",
  appInfo: "lab:app:info",
  settingsStatus: "lab:settings:status",
  settingsSetUrl: "lab:settings:set-url",
  settingsSetToken: "lab:settings:set-token",
  settingsClearToken: "lab:settings:clear-token",
  apiRequest: "lab:api:request",
  eventsSubscribe: "lab:events:subscribe",
  eventsUnsubscribe: "lab:events:unsubscribe",
  eventsEvent: "lab:events:event",
  saveReport: "lab:save-report",
} as const;

interface BridgeEvent {
  subscription_id: string;
  event: string;
  id: number | null;
  data: unknown;
}

const api = {
  engineUpdates: {
    status: () => ipcRenderer.invoke(IPC.updatesStatus),
    check: () => ipcRenderer.invoke(IPC.updatesCheck),
    setEnabled: (enabled: boolean) => ipcRenderer.invoke(IPC.updatesPreference, enabled),
    install: (family: string, assetId: number) => ipcRenderer.invoke(IPC.updatesInstall, family, assetId),
    remove: (buildId: string) => ipcRenderer.invoke(IPC.engineRemove, buildId),
  },
  runtime: {
    resetData: () => ipcRenderer.invoke(IPC.runtimeReset) as Promise<{ canceled: boolean }>,
    status: () => ipcRenderer.invoke(IPC.runtimeStatus),
    retry: () => ipcRenderer.invoke(IPC.runtimeRetry),
    select: (kind: string) => ipcRenderer.invoke(IPC.runtimeSelect, kind),
    useEngine: (id: string) => ipcRenderer.invoke(IPC.runtimeUseEngine, id),
    removeFolder: (kind: string, index: number) => ipcRenderer.invoke(IPC.runtimeRemoveFolder, kind, index),
  },
  appInfo: () => ipcRenderer.invoke(IPC.appInfo) as Promise<{
    version: string;
    platform: string;
    packaged: boolean;
    security?: Record<string, unknown>;
  }>,
  settings: {
    status: () => ipcRenderer.invoke(IPC.settingsStatus),
    setApiBaseUrl: (url: string) => ipcRenderer.invoke(IPC.settingsSetUrl, url),
    setToken: (token: string) => ipcRenderer.invoke(IPC.settingsSetToken, token),
    clearToken: () => ipcRenderer.invoke(IPC.settingsClearToken),
  },
  api: {
    request: (
      method: "GET" | "POST",
      path: string,
      body?: unknown,
      idempotencyKey?: string | null,
    ) => ipcRenderer.invoke(IPC.apiRequest, method, path, body, idempotencyKey ?? null),
    subscribeEvents: (experimentId: string, lastEventId: number) =>
      ipcRenderer.invoke(IPC.eventsSubscribe, experimentId, lastEventId) as Promise<string>,
    unsubscribeEvents: (subscriptionId: string) =>
      ipcRenderer.invoke(IPC.eventsUnsubscribe, subscriptionId) as Promise<void>,
    onEvent: (listener: (event: BridgeEvent) => void): (() => void) => {
      const wrapped = (_event: Electron.IpcRendererEvent, payload: unknown): void => {
        if (typeof payload !== "object" || payload === null) return;
        const value = payload as Partial<BridgeEvent>;
        if (typeof value.subscription_id !== "string" || typeof value.event !== "string") return;
        const id = typeof value.id === "number" && Number.isSafeInteger(value.id) ? value.id : null;
        listener({ subscription_id: value.subscription_id, event: value.event, id, data: value.data });
      };
      ipcRenderer.on(IPC.eventsEvent, wrapped);
      return () => ipcRenderer.removeListener(IPC.eventsEvent, wrapped);
    },
  },
  saveReport: (suggestedName: string, content: string) =>
    ipcRenderer.invoke(IPC.saveReport, suggestedName, content) as Promise<{
      canceled: boolean;
      path?: string;
    }>,
};

contextBridge.exposeInMainWorld("labDesktop", Object.freeze(api));
