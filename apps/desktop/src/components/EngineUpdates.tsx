import { useState } from "react";
import { usePolling } from "../lib/hooks";
import type { EngineUpdateStatus } from "../lib/bridge";
import { Badge, ErrorNotice, Modal, Notice } from "./ui";

function useEngineUpdates() {
  return usePolling<EngineUpdateStatus | null>(() => window.labDesktop?.engineUpdates?.status() ?? Promise.resolve(null), 1500);
}

export function EngineUpdatesPanel() {
  const poll = useEngineUpdates();
  const runtime = usePolling(() => window.labDesktop?.runtime?.status() ?? Promise.resolve(null), 1500);
  const [family, setFamily] = useState<"llamacpp" | "strata">("llamacpp");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [assets, setAssets] = useState<Record<string, number>>({});
  if (!poll.data) return null;
  const status = poll.data;
  const act = async (operation: () => Promise<unknown> | undefined) => {
    setBusy(true); setError(null);
    try { await operation(); poll.refresh(); }
    catch (caught) { setError(caught); }
    finally { setBusy(false); }
  };
  const waiting = busy || status.checking || !!status.operation;
  const installation = status.installation;
  const installedBuild = runtime.data?.engine_candidates?.find(build => build.engine_id === installation?.engine_id && Object.values(build.paths).some(value => value?.includes(`${installation.engine_id}-${installation.asset_id}/`)));
  const selectedBuild = installedBuild && Object.entries(installedBuild.paths).every(([key, value]) => runtime.data?.config[key as keyof typeof runtime.data.config] === value);
  return <section className="engine-updates" aria-label="Engine updates">
    <div className="engine-update-heading"><div><h3>Engine updates</h3><p className="muted">Official llama.cpp and Strata releases. Installs keep your existing builds until you choose to remove them.</p></div><button className="button button-secondary" disabled={waiting} onClick={() => void act(() => window.labDesktop?.engineUpdates?.check())}>{status.checking ? "Checking…" : "Check for updates"}</button></div>
    <label className="checkbox"><input type="checkbox" checked={status.enabled} disabled={busy} onChange={e => void act(() => window.labDesktop?.engineUpdates?.setEnabled(e.target.checked))} />Check official releases at startup and suggest updates</label>
    {error ? <ErrorNotice error={error} /> : null}
    {status.error ? <p role="status" className="muted">{status.error} Your installed engines remain available.</p> : null}
    {status.operation ? <div role="status" aria-live="polite"><strong>{status.operation}</strong><progress aria-label="Engine download" max={installation?.bytes_total || 1} value={installation?.phase === "downloading" && installation.bytes_total ? installation.bytes_done : undefined} />{installation?.bytes_total ? <p>{Math.floor(100 * installation.bytes_done / installation.bytes_total)}% downloaded · {Math.floor(installation.bytes_done / 1024 ** 2)} / {Math.ceil(installation.bytes_total / 1024 ** 2)} MiB. {installation.phase === "unpacking" ? "Checking and unpacking files; installation is not finished yet." : "Keep the app open until installation finishes."}</p> : null}</div> : null}
    {installation?.phase === "complete" && !status.operation ? <Notice tone="ok" title={`${installation.engine_id === "llamacpp" ? "llama.cpp" : "Strata"} ${installation.version} installed`}><p>{selectedBuild ? "This build is selected for new experiments. Existing results are unchanged." : "Download and archive verification finished. Select the build before starting a new optimization."}</p>{installedBuild && !selectedBuild ? <button className="button button-primary" disabled={waiting || runtime.data?.state === "starting"} onClick={() => void act(async () => { await window.labDesktop?.runtime?.useEngine?.(installedBuild.id); runtime.refresh(); })}>Use this engine</button> : !installedBuild ? <button className="button button-secondary" onClick={() => { window.location.hash = "#/settings"; }}>Review engine setup</button> : null}</Notice> : null}
    {message ? <p role="status">{message}</p> : null}
    <div className="tabs" role="group" aria-label="Choose engine family">{(["llamacpp", "strata"] as const).map(id => <button key={id} className={`tab ${family === id ? "active" : ""}`} aria-pressed={family === id} onClick={() => setFamily(id)}>{id === "llamacpp" ? "llama.cpp" : "Strata"}</button>)}</div>
    {!status.releases.length && !status.checking ? <p className="muted">{status.checked_at ? "Add an inference folder to check its engines." : "Check releases to see available updates."}</p> : null}
    {status.releases.filter(release => release.engine_id === family).map(release => {
      const recommendation = release.recommendation;
      const chosen = assets[release.engine_id] ?? (installation?.phase === "complete" && installation.engine_id === release.engine_id ? installation.asset_id : recommendation?.asset_id) ?? 0;
      const asset = release.assets.find(item => item.id === chosen);
      const alreadyInstalled = installation?.phase === "complete" && installation.engine_id === release.engine_id && installation.asset_id === chosen;
      return <div className="engine-release" key={release.engine_id}>
        <div><strong>{release.engine_id === "llamacpp" ? "llama.cpp" : "Strata"} {release.version}</strong> <Badge tone={release.update === "available" ? "warn" : "info"}>{alreadyInstalled ? "Installed · select to use" : release.update === "available" ? "Update available" : release.update === "current" ? "Current or newer installed" : "Version comparison needs review"}</Badge><small>Previously selected: {release.installed_version ?? "unknown"}</small></div>
        <div className="engine-fit">{recommendation?.asset_id ? <Badge tone="ok">Recommended for your hardware</Badge> : <Badge tone="warn">Compatibility needs review</Badge>}<strong>{recommendation?.label ?? "Checking hardware compatibility"}</strong><p>{recommendation?.hardware ?? "Hardware information is not available yet"}</p><p className="muted">{recommendation?.reason ?? "Refresh the update check to detect compatible builds."}</p>{asset ? <small>Selected build: {asset.name}</small> : null}</div>
        <div className="button-row"><button className="button button-primary" disabled={waiting || alreadyInstalled || !asset || (release.engine_id === "strata" && !release.support)} onClick={() => void act(async () => { setMessage(""); const result = await window.labDesktop?.engineUpdates?.install(release.engine_id, chosen); if (result?.canceled) setMessage("Installation canceled. Your selected engine is unchanged."); runtime.refresh(); })}>{alreadyInstalled ? "Build installed" : chosen && chosen === recommendation?.asset_id ? "Install recommended update…" : "Install custom build…"}</button>{asset ? <span className="muted">{alreadyInstalled ? "Archive" : "Download"} {Math.ceil((asset.download_size ?? asset.size + (release.support?.size ?? 0)) / 1024 ** 2)} MiB</span> : null}</div>
        <details className="engine-update-advanced"><summary>Advanced: choose another build</summary><label>Available Linux builds<select value={chosen || ""} disabled={waiting} onChange={e => setAssets(old => ({ ...old, [release.engine_id]: Number(e.target.value) }))}><option value="">No build selected</option>{release.assets.map(item => <option key={item.id} value={item.id}>{item.name}{item.id === recommendation?.asset_id ? " · recommended" : ""}</option>)}</select></label><small>Manual choices may require different hardware or drivers.</small></details>
      </div>;
    })}

    <small className="muted">We select a build from your detected hardware and driver capabilities. Downloads are checksum-verified; a recommendation is a compatibility match, not a measured performance claim.</small>
  </section>;
}

export function StartupUpdateSuggestion() {
  const poll = useEngineUpdates();
  const [dismissed, setDismissed] = useState(false);
  const [review, setReview] = useState(false);
  const offers = poll.data?.releases.filter(release => release.update !== "current") ?? [];
  if (!poll.data?.enabled || !offers.length || dismissed) return null;
  return <Modal title={offers.some(r => r.update === "available") ? "Engine updates available" : "Engine releases to review"} onClose={() => setDismissed(true)}><p>{offers.map(release => `${release.engine_id === "llamacpp" ? "llama.cpp" : "Strata"} ${release.version}`).join(" and ")} can be reviewed and installed.</p><p className="muted">Your installed builds keep working. Installation requires your approval.</p>{review ? <EngineUpdatesPanel /> : null}<div className="button-row"><button className="button button-secondary" onClick={() => setDismissed(true)}>Later</button>{!review ? <button className="button button-primary" onClick={() => setReview(true)}>Review updates</button> : null}</div></Modal>;
}
