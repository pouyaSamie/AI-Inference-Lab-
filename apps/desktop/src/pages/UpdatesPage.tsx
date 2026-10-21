import { usePolling } from "../lib/hooks";
import { relativeTime, shortId } from "../lib/format";
import { Badge, EmptyState, ErrorNotice, Notice, PageHeader, Panel, Spinner } from "../components/ui";
import type { PageProps } from "./types";

export function UpdatesPage({ api, navigate }: PageProps) {
  const workers = usePolling(() => api.workers(), 30_000);

  return (
    <>
      <PageHeader
        eyebrow="Release intelligence"
        title="Updates"
        description="Engine and model update notices are a later phase. This page never invents a release feed or downloads a binary."
        actions={<button className="button button-secondary" onClick={() => navigate("engines")}>Inspect installed engines</button>}
      />
      <Notice tone="info" title="Update intelligence is not implemented in this phase">
        <p>
          The controller records installed engine versions and hashes from worker snapshots. It does not query upstream
          release channels, download engines, replace binaries, or recommend unsolicited upgrades. Those actions require
          Phase 7 release intelligence and explicit operator approval.
        </p>
      </Notice>

      <Panel title="Observed installed builds" subtitle="Read from registered worker snapshots, not from the network.">
        {workers.error ? <ErrorNotice error={workers.error} onRetry={workers.refresh} /> : null}
        {!workers.data ? <Spinner label="Loading worker list" /> : null}
        {workers.data?.workers.length === 0 ? (
          <EmptyState title="No workers registered" detail="No installed build can be observed without a worker snapshot." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Worker</th><th>Status</th><th>Snapshot</th><th>Last heartbeat</th><th>Update feed</th></tr></thead>
              <tbody>
                {workers.data?.workers.map((worker) => (
                  <tr key={worker.worker_id}>
                    <td><strong>{worker.name}</strong><small>{shortId(worker.worker_id, 20)}</small></td>
                    <td>{worker.status}</td>
                    <td>{worker.snapshot_revision > 0 ? `revision ${worker.snapshot_revision}` : "no snapshot"}</td>
                    <td>{relativeTime(worker.last_heartbeat_at)}</td>
                    <td><Badge tone="warn">not implemented</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Safe update rules" subtitle="These boundaries are deliberate and enforced outside the UI.">
        <ul className="warning-list">
          <li>Never download, replace, or patch an engine or model from the operator UI.</li>
          <li>Never install a binary silently or as a side effect of opening a screen.</li>
          <li>Pin the engine and executable hash used by a validated recipe.</li>
          <li>A newer build invalidates the previous hash evidence until it is re-verified and re-benchmarked.</li>
          <li>Upstream release checks, if added later, must be read-only and explicit.</li>
        </ul>
      </Panel>
    </>
  );
}
