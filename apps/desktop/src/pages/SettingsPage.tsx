import { ResetDataPanel } from "../components/ResetData";
import { EngineUpdatesPanel } from "../components/EngineUpdates";
import { useEffect, useState } from "react";
import { LocalRuntimePanel, useLocalRuntime } from "../components/LocalRuntime";
import type { BridgeSettingsStatus } from "../lib/bridge";
import { humanEnum } from "../lib/format";
import { Badge, ErrorNotice, KeyValues, Notice, PageHeader, Panel, Spinner } from "../components/ui";
import type { PageProps } from "./types";

interface SettingsPageProps extends PageProps {
  demoEnabled: boolean;
  onDemoChange: (enabled: boolean) => void;
}

export function SettingsPage({ api, status, demoEnabled, onDemoChange }: SettingsPageProps) {
  const managed = useLocalRuntime();
  const [followSystem, setFollowSystem] = useState(() => (localStorage.getItem("lab.theme") ?? "system") === "system");
  const [bridge, setBridge] = useState<BridgeSettingsStatus | null>(null);
  const [appInfo, setAppInfo] = useState<{ version: string; platform: string; packaged: boolean; security?: Record<string, unknown> } | null>(null);
  const [apiUrl, setApiUrl] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [connection, setConnection] = useState<{ ok: boolean; detail: string } | null>(null);

  useEffect(() => {
    const update = () => setFollowSystem((localStorage.getItem("lab.theme") ?? "system") === "system");
    window.addEventListener("lab:appearance-changed", update);
    return () => window.removeEventListener("lab:appearance-changed", update);
  }, []);
  useEffect(() => {
    let stopped = false;
    void api
      .settingsStatus()
      .then((status) => {
        if (stopped) return;
        setBridge(status);
        setApiUrl(status.api_base_url);
      })
      .catch((caught: unknown) => {
        if (!stopped) setError(caught);
      });
    void api
      .appInfo()
      .then((info) => {
        if (!stopped) setAppInfo(info);
      })
      .catch(() => undefined);
    return () => {
      stopped = true;
    };
  }, [api]);

  const run = async (name: string, action: () => Promise<BridgeSettingsStatus | void>, success: string) => {
    setBusy(name);
    setError(null);
    setMessage(null);
    try {
      const next = await action();
      if (next) {
        setBridge(next);
        setApiUrl(next.api_base_url);
      }
      setMessage(success);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(null);
    }
  };

  const testConnection = async () => {
    setBusy("test");
    setError(null);
    setConnection(null);
    try {
      const status = await api.status();
      setConnection({
        ok: true,
        detail: `${status.service} ${status.version} · API ${status.api_version} · ${status.workers_online} worker(s) online`,
      });
    } catch (caught) {
      setConnection({
        ok: false,
        detail: caught instanceof Error ? caught.message : "Controller request failed",
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Desktop security and backend"
        title="Settings"
        description="The renderer has no Node.js access. API calls, the bearer token and report exports are proxied through the validated IPC bridge."
        actions={<Badge tone={demoEnabled ? "simulated" : "info"}>{demoEnabled ? "Offline demo" : "Live backend"}</Badge>}
      />

      <Panel title="Appearance" subtitle="The header toggle switches between light and dark.">
        <label className="checkbox-row"><input type="checkbox" checked={followSystem} onChange={event => {
          setFollowSystem(event.target.checked);
          localStorage.setItem("lab.theme", event.target.checked ? "system" : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
          window.dispatchEvent(new Event("lab:appearance-changed"));
        }} />Follow system appearance</label>
      </Panel>
      {error ? <ErrorNotice error={error} /> : null}
      {message ? <Notice tone="ok" title="Saved">{message}</Notice> : null}

      {!demoEnabled ? <><LocalRuntimePanel /><EngineUpdatesPanel /></> : null}
      {!managed.data ? <div className="grid-2">
        <Panel title="Backend connection" subtitle="HTTP is allowed only for loopback hosts. Use HTTPS for any remote controller.">
          {!bridge ? !error ? <Spinner label="Reading desktop settings" /> : <p>Settings unavailable. Reopen Settings to retry the secure bridge.</p> : (
            <>
              <label className="field">
                <span>Controller API base URL</span>
                <input
                  type="url"
                  value={apiUrl}
                  onChange={(event) => setApiUrl(event.target.value)}
                  placeholder="http://127.0.0.1:8787"
                  disabled={demoEnabled || busy !== null}
                  spellCheck={false}
                />
              </label>
              <div className="button-row">
                <button
                  className="button button-primary"
                  disabled={demoEnabled || busy !== null}
                  onClick={() =>
                    run(
                      "url",
                      () => api.setApiBaseUrl(apiUrl),
                      "Controller URL stored. The IPC proxy will use it for subsequent requests.",
                    )
                  }
                >
                  {busy === "url" ? "Saving…" : "Save URL"}
                </button>
                <button
                  className="button button-secondary"
                  onClick={testConnection}
                  disabled={demoEnabled || busy !== null}
                  title={demoEnabled ? "Disable demo mode to test the live controller" : undefined}
                >
                  {busy === "test" ? "Testing…" : "Test connection"}
                </button>
              </div>
              {connection ? (
                <Notice tone={connection.ok ? "ok" : "danger"} title={connection.ok ? "Controller reachable" : "Controller unreachable"}>
                  {connection.detail}
                </Notice>
              ) : null}
              <KeyValues
                items={[
                  { label: "URL in use", value: <span className="mono wrap">{bridge.api_base_url}</span> },
                  { label: "Token configured", value: bridge.token_configured ? "yes" : "no" },
                  { label: "Secure storage", value: bridge.secure_storage_available ? "available" : "unavailable" },
                  { label: "Storage backend", value: humanEnum(bridge.storage_backend) },
                  { label: "Token persistence", value: bridge.persistent ? "encrypted on disk" : "session memory only" },
                ]}
              />
              <p className="muted">{bridge.note}</p>
            </>
          )}
        </Panel>

        <Panel title="Operator bearer token" subtitle="The token is never returned to the renderer after storage.">
          {demoEnabled ? (
            <Notice tone="warn" title="Demo mode does not use credentials">
              Turn demo mode off to configure the live controller.
            </Notice>
          ) : (
            <>
              <label className="field">
                <span>New operator token</span>
                <input
                  type="password"
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  placeholder="Paste the operator bearer token"
                  autoComplete="new-password"
                  spellCheck={false}
                />
              </label>
              <div className="button-row">
                <button
                  className="button button-primary"
                  disabled={!token || busy !== null}
                  onClick={() =>
                    run(
                      "token",
                      async () => {
                        const next = await api.setToken(token);
                        setToken("");
                        return next;
                      },
                      "Token stored. It is not echoed back to this page.",
                    )
                  }
                >
                  {busy === "token" ? "Saving…" : "Store token"}
                </button>
                <button
                  className="button button-danger"
                  disabled={busy !== null}
                  onClick={() => {
                    if (!window.confirm("Clear the stored operator token?")) return;
                    void run("clear", () => api.clearToken(), "Operator token cleared.");
                  }}
                >
                  {busy === "clear" ? "Clearing…" : "Clear token"}
                </button>
              </div>
              {bridge && !bridge.secure_storage_available ? (
                <Notice tone="warn" title="OS keyring unavailable">
                  This environment cannot encrypt secrets. The token is kept only in the Electron main process for the
                  current session and is never written in plaintext.
                </Notice>
              ) : null}
            </>
          )}
        </Panel>
      </div>

      : null}

      <div className="grid-2">
        <Panel title="Data source" subtitle="Demo mode is explicit, local and clearly labelled across every screen.">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={demoEnabled}
              onChange={(event) => {
                onDemoChange(event.target.checked);
                setMessage(
                  event.target.checked
                    ? "Offline demo mode enabled. No controller or worker is contacted."
                    : "Demo mode disabled. The app will use the configured controller.",
                );
              }}
            />
            Use offline demo fixtures
          </label>
          <p className="muted">
            Demo mode is for UI inspection only. It cannot create real evidence, recipes or promotions. The controller
            remains the sole authority for qualification.
          </p>
        </Panel>

        <Panel title="Desktop security posture" subtitle="Defaults are enforced in the Electron main process.">
          <KeyValues
            items={[
              { label: "App version", value: appInfo?.version ?? "unknown" },
              { label: "Packaged", value: appInfo?.packaged ? "yes" : "development" },
              { label: "Platform", value: appInfo?.platform ?? navigator.platform },
              { label: "Context isolation", value: "enabled" },
              { label: "Node integration", value: "disabled" },
              { label: "Sandbox", value: "enabled" },
              { label: "Hardware acceleration", value: String(appInfo?.security?.hardware_acceleration ?? "disabled") },
              { label: "Navigation / new windows", value: "blocked" },
              { label: "Permissions", value: "denied" },
              { label: "IPC API", value: "allowlisted /api/v1 routes only" },
            ]}
          />
          <ul className="warning-list">
            <li>The renderer has no filesystem/Node access, bearer token or environment dump.</li>
            <li>Report export uses a native save dialog with bounded content size.</li>
            <li>Event streams are proxied through the main process so the bearer token stays out of the page.</li>
            <li>Hardware acceleration is disabled before Electron becomes ready.</li>
            <li>
              <span className="mono">LAB_DESKTOP_ENABLE_GPU=1</span> is an explicit operator override that requires a
              restart; any shared-GPU qualification then needs contamination verification.
            </li>
          </ul>
        </Panel>
      </div>
      <ResetDataPanel demo={demoEnabled} runtime={managed.data} status={status} />
    </>
  );
}
