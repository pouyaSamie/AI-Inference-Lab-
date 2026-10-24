import { useLocalRuntime } from "../components/LocalRuntime";
import { ModelVerificationProgress } from "../components/ModelVerification";
import { useEffect, useState } from "react";
import { usePolling } from "../lib/hooks";
import { formatBytes, shortId } from "../lib/format";
import { PageHeader, Panel, EmptyState, ErrorNotice, Badge, Spinner, KeyValues, Notice } from "../components/ui";
import type { PageProps } from "./types";
import type { ModelArtifact, WorkerSnapshot } from "../lib/contracts";

function hashState(model: ModelArtifact): { label: string; tone: "ok" | "warn" | "danger" } {
  const files = model.files ?? [];
  if (files.length === 0) return { label: "No files listed", tone: "warn" };
  const missing = files.filter((file) => !file.sha256);
  if (missing.length > 0) return { label: "Not verified", tone: "warn" };
  if (!model.verified) return { label: "Hashes present, not verified", tone: "warn" };
  return { label: "Verified hashes", tone: "ok" };
}

function Inventory({ api, workerId }: { api: PageProps["api"]; workerId: string }) {
  const snapshot = usePolling(() => api.workerSnapshot(workerId), 3000);
  const runtime = useLocalRuntime();
  const verification = api.demo ? undefined : runtime.data?.inventory?.verification;
  const [query, setQuery] = useState("");
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
  const allModels = data.models ?? [];
  const models = allModels.filter(model => `${model.display_name} ${model.model_id} ${model.quantization ?? ""}`.toLowerCase().includes(query.toLowerCase().trim()));
  const selected = models.find((model) => model.model_id === selectedModelId) ?? models[0];

  return (
    <div className="grid-2 inventory-grid">
      <div className="model-inventory-column"><ModelVerificationProgress value={verification} /><Panel
        title="Discovered models"
        subtitle={`Snapshot revision ${data.revision} · ${data.models?.length ?? 0} model(s)`}
      >
        <label className="field"><span>Find model</span><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Model name, identity or quantization" /></label>
        <p className="muted" role="status">{models.length} of {allModels.length} models</p>
        {models.length === 0 ? (
          <EmptyState
            title={query ? "No matching models" : "No models in the snapshot"}
            detail="The worker has not observed a compatible model under an allowlisted root."
          />
        ) : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table">
            <table>
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  <th scope="col">Quant</th>
                  <th scope="col" className="numeric">Size</th>
                  <th scope="col">Hashes</th>
                  <th scope="col">Engines</th>
                </tr>
              </thead>
              <tbody>
                {models.map((model) => {
                  const state = hashState(model);
                  if (!model.verified && verification && ["queued", "verifying"].includes(verification.state)) {
                    if (verification.model_id === model.model_id || model.files?.some(file => file.path === verification.current_path)) state.label = "Verifying…";
                    else if (!verification.model_id) state.label = "Queued for verification";
                  }
                  return (
                    <tr
                      key={model.model_id}
                      className={`clickable ${selected?.model_id === model.model_id ? "selected" : ""}`}
                      onClick={() => setSelectedModelId(model.model_id)}
                    >
                      <td>
                        <button className="link-button" aria-pressed={selected?.model_id === model.model_id} onClick={() => setSelectedModelId(model.model_id)}>{model.display_name}</button>
                        <small>{model.model_id}</small>
                      </td>
                      <td>{model.quantization ?? "unknown"}</td>
                      <td className="numeric">{formatBytes(model.size_bytes)}</td>
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

      </div><Panel title="Artifact detail" subtitle="Path and hash evidence is read-only.">
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
            {!selected.verified ? <Notice tone="warn" title="This model is not ready for an experiment"><p>Check the file list below for missing hashes or split files. Keep all shards together and check file permissions, then use Rescan folders in Settings. Hash verification establishes file identity; preflight still checks whether your context fits.</p><button className="button button-secondary" onClick={() => { window.location.hash = "#/settings"; }}>Open model setup</button></Notice> : null}
            <h3 className="subsection-title">Files</h3>
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Path</th>
                    <th scope="col" className="numeric">Size</th>
                    <th scope="col">SHA-256</th>
                    <th scope="col">Shard</th>
                  </tr>
                </thead>
                <tbody>
                  {(selected.files ?? []).map((file) => (
                    <tr key={file.path}>
                      <td><span className="mono wrap">{file.path}</span></td>
                      <td className="numeric">{formatBytes(file.size_bytes)}</td>
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
  const workers = usePolling(() => api.workers(), 3_000);
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
      {!workers.data && !workers.error ? <Spinner label="Loading workers" /> : null}
      {workers.error ? <ErrorNotice error={workers.error} onRetry={workers.refresh} /> : null}
      {workerId ? (
        <Inventory key={workerId} api={api} workerId={workerId} />
      ) : workers.data ? (
        <Panel>
          <EmptyState
            title="Select a worker"
            detail="Model discovery is scoped to each worker's allowlisted roots. There is no client-side filesystem picker for remote models."
          />
        </Panel>
      ) : null}
    </>
  );
}
