import { useEffect, useState } from "react";
import { usePolling } from "../lib/hooks";
import { formatBytes, shortId } from "../lib/format";
import { PageHeader, Panel, EmptyState, ErrorNotice, Badge, Spinner, KeyValues } from "../components/ui";
import type { PageProps } from "./types";
import type { ModelArtifact, WorkerSnapshot } from "../lib/contracts";

function hashState(model: ModelArtifact): { label: string; tone: "ok" | "warn" | "danger" } {
  const files = model.files ?? [];
  if (files.length === 0) return { label: "No files listed", tone: "warn" };
  const missing = files.filter((file) => !file.sha256);
  if (missing.length > 0) return { label: `${missing.length} file hash(es) missing`, tone: "danger" };
  if (!model.verified) return { label: "Hashes present, not verified", tone: "warn" };
  return { label: "Verified hashes", tone: "ok" };
}

function Inventory({ api, workerId }: { api: PageProps["api"]; workerId: string }) {
  const snapshot = usePolling(() => api.workerSnapshot(workerId), 30_000);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedModelId && snapshot.data?.models?.length) {
      setSelectedModelId(snapshot.data.models[0]!.model_id);
    }
  }, [selectedModelId, snapshot.data]);

  if (snapshot.loading && !snapshot.data) return <Spinner label="Reading cached inventory" />;
  if (snapshot.error) return <ErrorNotice error={snapshot.error} onRetry={snapshot.refresh} />;
  if (!snapshot.data) return <EmptyState title="No cached snapshot" detail="Run a worker scan first." />;

  const data: WorkerSnapshot = snapshot.data;
  const models = data.models ?? [];
  const selected = models.find((model) => model.model_id === selectedModelId) ?? models[0];

  return (
    <div className="grid-2 inventory-grid">
      <Panel
        title="Discovered models"
        subtitle={`Snapshot revision ${data.revision} · ${data.models?.length ?? 0} model(s)`}
        actions={<button className="link-button" onClick={snapshot.refresh}>Refresh snapshot</button>}
      >
        {models.length === 0 ? (
          <EmptyState
            title="No models in the snapshot"
            detail="The worker has not observed a compatible model under an allowlisted root."
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Quant</th>
                  <th>Size</th>
                  <th>Hashes</th>
                  <th>Engines</th>
                </tr>
              </thead>
              <tbody>
                {models.map((model) => {
                  const state = hashState(model);
                  return (
                    <tr
                      key={model.model_id}
                      className={`clickable ${selected?.model_id === model.model_id ? "selected" : ""}`}
                      onClick={() => setSelectedModelId(model.model_id)}
                    >
                      <td>
                        <strong>{model.display_name}</strong>
                        <small>{model.model_id}</small>
                      </td>
                      <td>{model.quantization ?? "unknown"}</td>
                      <td>{formatBytes(model.size_bytes)}</td>
                      <td><Badge tone={state.tone}>{state.label}</Badge></td>
                      <td>{(model.compatible_engines ?? []).join(", ") || "unknown"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Artifact detail" subtitle="Path and hash evidence is read-only.">
        {!selected ? (
          <EmptyState title="Select a model" />
        ) : (
          <>
            <KeyValues
              items={[
                { label: "Model ID", value: selected.model_id },
                { label: "Family", value: selected.model_family ?? "unknown" },
                { label: "Architecture", value: selected.architecture },
                { label: "Quantization", value: selected.quantization ?? "unknown" },
                { label: "Tokenizer", value: selected.tokenizer_id ?? "not observed" },
                { label: "Context metadata", value: selected.metadata_context_tokens ?? "unknown" },
                { label: "Path map", value: (selected.path_map ?? []).join(", ") || "not recorded" },
              ]}
            />
            <h3 className="subsection-title">Files</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Path</th>
                    <th>Size</th>
                    <th>SHA-256</th>
                    <th>Shard</th>
                  </tr>
                </thead>
                <tbody>
                  {(selected.files ?? []).map((file) => (
                    <tr key={file.path}>
                      <td><span className="mono wrap">{file.path}</span></td>
                      <td>{formatBytes(file.size_bytes)}</td>
                      <td>{file.sha256 ? <span className="mono">{shortId(file.sha256, 18)}</span> : <Badge tone="danger">missing</Badge>}</td>
                      <td>{file.shard_index ?? "—"} / {file.shard_count ?? "—"}</td>
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

export function ModelsPage({ api }: PageProps) {
  const workers = usePolling(() => api.workers(), 30_000);
  const [workerId, setWorkerId] = useState<string | null>(null);

  useEffect(() => {
    if (!workerId && workers.data?.workers.length) setWorkerId(workers.data.workers[0]!.worker_id);
  }, [workerId, workers.data]);

  return (
    <>
      <PageHeader
        eyebrow="Scoped discovery"
        title="Models"
        description="Models are selected only from worker-authorized roots. This page reads cached snapshots and never browses the remote filesystem."
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
      {workers.error ? <ErrorNotice error={workers.error} onRetry={workers.refresh} /> : null}
      {workerId ? (
        <Inventory key={workerId} api={api} workerId={workerId} />
      ) : (
        <Panel>
          <EmptyState
            title="Select a worker"
            detail="Model discovery is scoped to each worker's allowlisted roots. There is no client-side filesystem picker for remote models."
          />
        </Panel>
      )}
    </>
  );
}
