import { useEffect, useState } from "react";
import { usePolling } from "../lib/hooks";
import { shortId } from "../lib/format";
import { PageHeader, Panel, EmptyState, ErrorNotice, Badge, Spinner, KeyValues } from "../components/ui";
import type { PageProps } from "./types";
import type { EngineCapabilityManifest, WorkerSnapshot } from "../lib/contracts";

function supportTone(support: string | undefined): "ok" | "warn" | "danger" | "neutral" {
  if (support === "supported") return "ok";
  if (support === "conditional") return "warn";
  if (support === "unsupported") return "danger";
  return "neutral";
}

function Inventory({ api, workerId }: { api: PageProps["api"]; workerId: string }) {
  const snapshot = usePolling(() => api.workerSnapshot(workerId), 30_000);
  const [engineId, setEngineId] = useState<string | null>(null);

  useEffect(() => {
    if (!engineId && snapshot.data?.engines?.length) {
      setEngineId(snapshot.data.engines[0]!.engine.engine_id);
    }
  }, [engineId, snapshot.data]);

  if (snapshot.loading && !snapshot.data) return <Spinner label="Reading cached engine manifests" />;
  if (snapshot.error) return <ErrorNotice error={snapshot.error} onRetry={snapshot.refresh} />;
  if (!snapshot.data) return <EmptyState title="No cached snapshot" />;

  const data: WorkerSnapshot = snapshot.data;
  const engines = data.engines ?? [];
  const selected: EngineCapabilityManifest | undefined =
    engines.find((engine) => engine.engine.engine_id === engineId) ?? engines[0];

  return (
    <div className="grid-2 inventory-grid">
      <Panel
        title="Installed engines"
        subtitle={`Snapshot revision ${data.revision} · observed capability manifests`}
      >
        {engines.length === 0 ? (
          <EmptyState
            title="No engines discovered"
            detail="Configure the worker engine roots; the UI never launches or installs an engine."
          />
        ) : (
          <div className="engine-list">
            {engines.map((manifest) => (
              <button
                key={manifest.engine.engine_id}
                aria-pressed={selected?.engine.engine_id === manifest.engine.engine_id}
                className={`engine-card ${selected?.engine.engine_id === manifest.engine.engine_id ? "selected" : ""}`}
                onClick={() => setEngineId(manifest.engine.engine_id)}
              >
                <div>
                  <strong>{manifest.engine.engine_id}</strong>
                  <small>{manifest.engine.version} · build {manifest.engine.build}</small>
                </div>
                <Badge tone="info">{manifest.backend}</Badge>
                <span className="engine-card-hash mono">{shortId(manifest.engine.executable_sha256, 20)}</span>
              </button>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Capabilities" subtitle="Only flags observed from the installed build are shown.">
        {!selected ? (
          <EmptyState title="Select an engine" />
        ) : (
          <>
            <KeyValues
              items={[
                { label: "Engine", value: selected.engine.engine_id },
                { label: "Version", value: selected.engine.version },
                { label: "Build", value: selected.engine.build },
                { label: "Backend", value: selected.engine.backend },
                { label: "Executable", value: <span className="mono wrap">{selected.engine.executable_path ?? "not recorded"}</span> },
                { label: "Executable SHA-256", value: <span className="mono wrap">{selected.engine.executable_sha256}</span> },
                { label: "Source commit", value: selected.engine.source_commit ?? "not observed" },
                { label: "Help digest", value: selected.help_sha256 ? shortId(selected.help_sha256, 26) : "not recorded" },
              ]}
            />
            {selected.notes?.length ? (
              <ul className="warning-list">
                {selected.notes.map((note) => <li key={note}>{note}</li>)}
              </ul>
            ) : null}
            <h3 className="subsection-title">Observed parameters ({selected.descriptors?.length ?? 0})</h3>
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Key</th>
                    <th scope="col">Kind</th>
                    <th scope="col">Support</th>
                    <th scope="col">Range / values</th>
                    <th scope="col">Default</th>
                    <th scope="col">Impact</th>
                  </tr>
                </thead>
                <tbody>
                  {(selected.descriptors ?? []).map((descriptor) => (
                    <tr key={descriptor.key}>
                      <td className="mono">{descriptor.key}</td>
                      <td>{descriptor.kind}</td>
                      <td><Badge tone={supportTone(descriptor.support)}>{descriptor.support ?? "unknown"}</Badge></td>
                      <td className="mono">
                        {descriptor.legal_values?.length
                          ? descriptor.legal_values.map(String).join(", ")
                          : descriptor.minimum !== null && descriptor.maximum !== null
                            ? `${descriptor.minimum} … ${descriptor.maximum}`
                            : "not declared"}
                      </td>
                      <td className="mono">{descriptor.default === null || descriptor.default === undefined ? "none" : String(descriptor.default)}</td>
                      <td>{descriptor.impact_class ?? "P2"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}

export function EnginesPage({ api }: PageProps) {
  const workers = usePolling(() => api.workers(), 30_000);
  const [workerId, setWorkerId] = useState<string | null>(null);

  useEffect(() => {
    if (!workerId && workers.data?.workers.length) setWorkerId(workers.data.workers[0]!.worker_id);
  }, [workerId, workers.data]);

  return (
    <>
      <PageHeader
        eyebrow="Observed builds"
        title="Engines"
        description="Command capabilities differ by installed build. Unsupported or unobserved flags are never offered as if they were valid."
        actions={
          <label className="field-inline">
            <span>Worker</span>
            <select value={workerId ?? ""} onChange={(event) => setWorkerId(event.target.value || null)}>
              <option value="">Select worker</option>
              {workers.data?.workers.map((worker) => (
                <option key={worker.worker_id} value={worker.worker_id}>{worker.name}</option>
              ))}
            </select>
          </label>
        }
      />
      {!workers.data && !workers.error ? <Spinner label="Loading workers" /> : null}
      {workers.error ? <ErrorNotice error={workers.error} onRetry={workers.refresh} /> : null}
      {workerId ? <Inventory key={workerId} api={api} workerId={workerId} /> : workers.data ? <Panel><EmptyState title="Select a worker" /></Panel> : null}
    </>
  );
}
