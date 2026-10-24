import { useState } from "react";
import type { LocalRuntimeStatus } from "../lib/bridge";
import type { SystemStatusResponse } from "../lib/contracts";
import { ErrorNotice, Notice, Panel } from "./ui";

export function ResetDataPanel({ demo, runtime, status }: { demo: boolean; runtime: LocalRuntimeStatus | null; status: SystemStatusResponse | null }) {
  const [busy,setBusy]=useState(false), [error,setError]=useState<unknown>(null), [cancelled,setCancelled]=useState(false);
  const available = !demo && runtime?.managed && ["ready","needs_configuration"].includes(runtime.state) && !!window.labDesktop?.runtime?.resetData;
  const idle = status?.experiments_active === 0 && (status.serving_active ?? 0) === 0;
  const reset = async () => {
    if(!available || !idle || busy)return;
    setBusy(true);setError(null);setCancelled(false);
    try { const result=await window.labDesktop!.runtime!.resetData!();setCancelled(result.canceled); }
    catch(error){setError(error);}
    finally{setBusy(false);}
  };
  return <Panel title="Start fresh" subtitle="Reset this desktop's local lab data.">
    <p>Remove studies, recipes, cached inventory and verification, saved folders, preferences and credentials. The app restarts at setup.</p>
    <p className="muted">Model files and installed engine builds are kept. Lab records move to the system Trash for recovery; this is not secure erasure. Export records you need first. This action never resets a remote controller.</p>
    <button className="button button-danger" disabled={!available || !idle || busy} onClick={() => void reset()}>{busy ? "Resetting local data…" : "Reset local data…"}</button>
    {!available ? <p className="muted">Available only for a healthy desktop-managed local lab, outside demo mode.</p> : !idle ? <p className="muted">Finish or cancel active jobs and stop the recipe engine first. A reachable idle controller is required.</p> : <p className="muted">Requires confirmation in a native dialog. Cancel is the default.</p>}
    {cancelled ? <Notice tone="info" title="Reset cancelled">No data was changed.</Notice> : null}
    {error ? <ErrorNotice error={error} /> : null}
  </Panel>;
}
