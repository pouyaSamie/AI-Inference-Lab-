import { ModelVerificationProgress } from "./ModelVerification";
import { EngineUpdatesPanel } from "./EngineUpdates";
import { useState } from "react";
import type { LocalRuntimeStatus, RuntimePathKind } from "../lib/bridge";
import { usePolling } from "../lib/hooks";
import { Badge, ErrorNotice, Notice, Panel, WarningList } from "./ui";

const ADVANCED: [RuntimePathKind, string][] = [
  ["llama_server_path", "Select llama-server"], ["llama_bench_path", "Select llama-bench"],
  ["llama_lib_dir", "Select library directory"], ["strata_path", "Select Strata executable"],
  ["strata_server_script", "Select server script"], ["strata_python", "Select Python environment"],
];
const STEPS = ["Folders", "Engine builds", "Review & save"];
const STEP_KEY = "lab.setup.step";
const DONE_KEY = "lab.setup.complete";

export function useLocalRuntime() {
  return usePolling<LocalRuntimeStatus | null>(() => window.labDesktop?.runtime?.status() ?? Promise.resolve(null), 1000);
}

export function LocalRuntimePanel() {
  const runtime = useLocalRuntime();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [step, setStep] = useState(() => Math.min(2, Math.max(0, Number(localStorage.getItem(STEP_KEY)) || 0)));
  const [editing, setEditing] = useState(() => localStorage.getItem(DONE_KEY) !== "1");
  if (!runtime.data) return null;
  const status = runtime.data;
  const waiting = busy || status.state === "starting" || status.state === "stopped";
  const config = status.config;
  const inventory = status.inventory;
  const builds = status.engine_candidates ?? [];
  const nextStep = (next: number) => { setStep(next); localStorage.setItem(STEP_KEY, String(next)); };
  const act = async (operation: () => Promise<unknown> | undefined) => {
    setBusy(true); setError(null);
    try { await operation(); runtime.refresh(); }
    catch (caught) { setError(caught); }
    finally { setBusy(false); }
  };
  const select = (kind: RuntimePathKind) => void act(() => window.labDesktop?.runtime?.select(kind));
  const openModels = () => { window.location.hash = "#/models"; };
  const selected = builds.filter((build) => build.paths.llama_server_path === config.llama_server_path && !!config.llama_server_path || build.paths.strata_path === config.strata_path && !!config.strata_path);
  const hasEngine = !!(config.llama_server_path || config.strata_path);
  const folderList = (paths: string[], kind?: "model_roots" | "engine_roots") => paths.length ? <ul className="setup-paths">{paths.map((item, index) => <li key={item}><code>{item}</code>{kind ? <button className="link-button" disabled={waiting} aria-label={`Remove folder ${item}`} onClick={() => void act(() => window.labDesktop?.runtime?.removeFolder?.(kind, index))}>Remove</button> : null}</li>)}</ul> : <p className="muted">No folder selected yet</p>;

  return <Panel className="local-setup" title={editing ? "Set up your local lab" : "Local lab"} subtitle="Choose your folders once. Your selections are saved automatically; no API setup is needed." actions={!editing ? <button className="button button-secondary" onClick={() => { setEditing(true); localStorage.removeItem(DONE_KEY); window.dispatchEvent(new Event("lab:setup-changed")); }}>Edit setup</button> : undefined}>
    <Notice tone={status.state === "ready" ? "ok" : status.state === "error" ? "danger" : "info"} title={status.state === "ready" ? ((inventory?.verified_models ?? 0) < (inventory?.models ?? 0) ? "Services running · verification pending" : "Models verified · preflight required") : status.state === "starting" ? "Discovering your lab" : status.state === "error" ? "Needs attention" : "Setup in progress"}>{status.message}</Notice>
    {error ? <ErrorNotice error={error} /> : null}
    <ModelVerificationProgress value={inventory?.verification} />
    {inventory ? <div className="setup-summary" aria-label="Discovery summary"><span><strong>{inventory.models}</strong> models discovered</span><span><strong>{builds.length}</strong> engine builds found</span><span><strong>{inventory.gpus}</strong> GPUs detected</span></div> : null}

    {editing ? <>
      <nav className="setup-steps" aria-label="Setup steps">{STEPS.map((label, index) => <button key={label} aria-current={step === index ? "step" : undefined} className={step === index ? "active" : ""} onClick={() => nextStep(index)}><span>{index + 1}</span>{label}</button>)}</nav>
      {step === 0 ? <div className="setup-folders">
        <section className="setup-card"><div><h3>Model folders</h3><p>Add a parent folder. GGUF models, split files and Strata packs are discovered in its subfolders.</p></div>{folderList(config.model_roots, "model_roots")}<button className="button button-primary" disabled={waiting} onClick={() => select("model_roots")}>Add model folder</button></section>
        <section className="setup-card"><div><h3>Inference engines</h3><p>Select the folder containing your installed llama.cpp or Strata builds. Supporting files are detected together.</p></div>{folderList(config.engine_roots ?? [], "engine_roots")}<button className="button button-secondary" disabled={waiting} onClick={() => select("engine_roots")}>Add inference folder</button></section>
      </div> : null}
      {step === 1 ? <div className="setup-builds">
        <EngineUpdatesPanel />
        <p className="muted">Recommended marks the latest identifiable installed version with its supporting files present. Compatibility still needs verification.</p>
        {builds.length ? builds.map((build) => <section className="setup-build" key={build.id}><div><strong>{build.label}</strong>{build.recommended ? <Badge tone="ok">Recommended · latest installed</Badge> : null}{build.version ? <small>Version {build.version}{build.build_number != null ? ` · build ${build.build_number}` : ""} · {build.version_source}</small> : <small>Version not identified</small>}<code>{build.paths.llama_server_path ?? build.paths.strata_path}</code>{build.missing.length ? <p className="muted">Not found automatically: {build.missing.join(", ")}. Set these under Advanced if needed.</p> : <p className="muted">Executable and supporting files detected</p>}</div><div className="setup-build-actions">{selected.some((item) => item.id === build.id) ? <Badge tone="ok">Selected</Badge> : <button className="button button-primary" disabled={waiting} onClick={() => void act(() => window.labDesktop?.runtime?.useEngine?.(build.id))}>Use this build</button>}{window.labDesktop?.engineUpdates ? <button className="button button-secondary" disabled={waiting || selected.some(item => item.id === build.id)} onClick={() => void act(() => window.labDesktop?.engineUpdates?.remove(build.id))}>Remove build…</button> : null}</div></section>) : <div className="setup-empty"><strong>{config.engine_roots?.length ? "No supported executable found" : "Add an inference folder first"}</strong><p>We look for installed llama-server and Strata executables. Source files alone are not an installed build.</p><button className="button button-secondary" disabled={waiting} onClick={() => { nextStep(0); select("engine_roots"); }}>Choose inference folder</button></div>}
      </div> : null}
      {step === 2 ? <section className="setup-review"><h3>Review your setup</h3><dl className="key-values"><div><dt>Model folders</dt><dd>{folderList(config.model_roots)}</dd></div><div><dt>Selected engines</dt><dd>{selected.length ? selected.map((item) => item.label).join(", ") : hasEngine ? "Configured through advanced paths" : "Not selected yet"}</dd></div><div><dt>Inventory</dt><dd>{inventory ? `${inventory.models} models · ${inventory.verified_models} hash-verified` : "Waiting for a model scan"}</dd></div><div><dt>Optimization</dt><dd>{status.state === "ready" ? "Engine and GPU detected; file verification and preflight still apply" : status.message}</dd></div></dl><p className="muted">Models can be browsed before choosing an engine. Large files are hash-verified before an experiment, so adding a folder stays quick.</p></section> : null}
      <div className="setup-navigation"><button className="button button-secondary" disabled={step === 0} onClick={() => nextStep(step - 1)}>Back</button><span>Step {step + 1} of 3 · selections saved automatically</span>{step < 2 ? <button className="button button-primary" onClick={() => nextStep(step + 1)}>Continue</button> : <button className="button button-primary" onClick={() => { localStorage.setItem(DONE_KEY, "1"); setEditing(false); window.dispatchEvent(new Event("lab:setup-changed")); }}>Save setup</button>}</div>
      <details className="setup-advanced"><summary>Advanced: individual paths</summary><p>Only needed for unusual layouts or files that could not be detected together.</p><div className="setup-advanced-grid">{ADVANCED.map(([kind, label]) => <div key={kind}><span>{label.replace("Select ", "")}</span><code>{String(config[kind] ?? "Not selected")}</code><button className="button button-secondary" disabled={waiting} onClick={() => select(kind)}>{label}</button></div>)}</div></details>
    </> : <div className="setup-review"><dl className="key-values"><div><dt>Model folders</dt><dd>{folderList(config.model_roots)}</dd></div><div><dt>Selected engines</dt><dd>{selected.map((item) => item.label).join(", ") || (hasEngine ? "Advanced configuration" : "Choose an engine through Edit setup")}</dd></div></dl></div>}

    <footer className="setup-footer"><div className="button-row"><button className="button button-secondary" disabled={waiting} onClick={() => void act(() => window.labDesktop?.runtime?.retry())}>{status.state === "error" ? "Retry discovery" : "Rescan folders"}</button>{(inventory?.models ?? 0) > 0 ? <button className="button button-secondary" onClick={openModels}>View models</button> : null}</div><small>Your folders stay read-only. To change folders or builds, finish or cancel active jobs first.</small></footer>
    {inventory?.warnings?.length ? <details className="setup-warnings"><summary>Discovery details ({inventory.warnings.length})</summary><WarningList warnings={inventory.warnings} /></details> : null}
  </Panel>;
}
