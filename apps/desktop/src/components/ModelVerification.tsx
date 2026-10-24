import { useState } from "react";
import type { VerificationProgress } from "../lib/bridge";
import { formatBytes } from "../lib/format";
export function ModelVerificationProgress({ value }: { value?: VerificationProgress }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (!value) return null;
  const active = value.state === "queued" || value.state === "verifying";
  if (!active && !["failed", "complete"].includes(value.state)) return null;
  const stalled = active && value.updated_at != null && Date.now() / 1000 - value.updated_at > 120;
  const percent = value.bytes_total ? Math.min(100, Math.floor(100 * value.bytes_done / value.bytes_total)) : null;
  const retry = async () => {
    setError(""); setBusy(true);
    try { await window.labDesktop?.runtime?.retry(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not retry verification"); }
    finally { setBusy(false); }
  };
  return <section className="model-verification" role="status" aria-live="polite">
    <strong>{stalled ? "Verification has not reported progress for over 2 minutes" : value.state === "complete" ? "Model files verified" : value.state === "failed" ? "Some model files could not be verified" : value.state === "queued" ? "Waiting for the worker to verify files" : "Verifying imported models"}</strong>
    {active ? <progress aria-label="Model file verification" max={100} value={percent ?? undefined} /> : null}
    <span>{percent === null ? "File count and size are not available yet." : `${percent}% read · ${formatBytes(value.bytes_done)} of ${formatBytes(value.bytes_total)} · ${value.files_done}/${value.files_total} files`}</span>
    {value.current_file ? <small>Current file: {value.current_file}</small> : null}
    {stalled || value.state === "failed" ? <><p>Open Models and select an unverified model to inspect missing files and discovery warnings. Check that every split file is present, readable and unchanged. A slow disk can also pause progress; elapsed time alone does not prove failure.</p><div className="button-row"><button className="button button-secondary" onClick={() => { window.location.hash = "#/models"; }}>Inspect model files</button>{window.labDesktop?.runtime ? <button className="button button-secondary" disabled={busy} onClick={() => void retry()}>{busy ? "Requesting rescan…" : "Rescan & retry verification"}</button> : null}</div><small>Finish or cancel active experiments and stop recipe serving before rescanning. The app will refuse a rescan while they are active.</small></> : null}
    {error ? <p role="alert">{error}</p> : null}
    <small>{value.state === "complete" ? "Verification finished. Unchanged files reuse their verified hashes on the next startup." : active ? "You can keep browsing. Large model files can take several minutes; the worker reads them without changing them." : "Unverified models cannot start a qualified experiment. Verified models remain available."}</small>
  </section>;
}
