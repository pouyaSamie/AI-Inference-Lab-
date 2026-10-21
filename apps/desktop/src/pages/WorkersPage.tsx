import { useEffect, useState } from "react";
import { usePolling } from "../lib/hooks";
import { formatBytes, relativeTime, shortId } from "../lib/format";
import {
  PageHeader,
  Panel,
  EmptyState,
  ErrorNotice,
  Badge,
  StatusBadge,
  Spinner,
  KeyValues,
} from "../components/ui";
import type { PageProps } from "./types";
import type { GPUDevice, WorkerSnapshot } from "../lib/contracts";

function WorkerDetail({ api, workerId }: { api: PageProps["api"]; workerId: string }) {
  const snapshot = usePolling(() => api.workerSnapshot(workerId), 20_000);
  if (snapshot.loading && !snapshot.data) return <Spinner label="Reading cached worker snapshot" />;
  if (snapshot.error) return <ErrorNotice error={snapshot.error} onRetry={snapshot.refresh} />;
  if (!snapshot.data) return <EmptyState title="No snapshot" />;
  const data: WorkerSnapshot = snapshot.data;
  const hardware = data.hardware;
  const gpus: GPUDevice[] = hardware.gpus ?? [];
  const warnings = [
    ...(data.health.warnings ?? []),
    ...(hardware.contamination_warnings ?? []),
    ...(data.notes ?? []),
  ];

  return (
    <div className="grid-2">
      <Panel
        title="Hardware"
        subtitle={`Collected ${relativeTime(hardware.collected_at)} · snapshot revision ${data.revision}`}
        actions={<button className="link-button" onClick={snapshot.refresh}>Refresh snapshot</button>}
      >
        <KeyValues
          items={[
            { label: "Host", value: hardware.hostname },
            { label: "OS", value: `${hardware.os} · ${hardware.kernel}` },
            { label: "CPU", value: `${hardware.cpu_model} · ${hardware.cpu_threads} threads` },
            { label: "RAM", value: `${formatBytes(hardware.ram_available_bytes)} available / ${formatBytes(hardware.ram_total_bytes)}` },
            { label: "CUDA driver", value: hardware.cuda_driver_version ?? "unavailable" },
            { label: "CUDA runtime", value: hardware.cuda_runtime_version ?? "unavailable" },
          ]}
        />
        <h3 className="subsection-title">GPU devices</h3>
        {gpus.length === 0 ? (
          <EmptyState title="No GPU observed" detail="The worker did not report a GPU device." />
        ) : (
          <div className="gpu-grid">
            {gpus.map((gpu) => (
              <div className="gpu-card" key={gpu.uuid}>
                <div className="gpu-card-top">
                  <strong>{gpu.name}</strong>
                  <Badge tone={gpu.owned_by_lab ? "info" : "warn"}>{gpu.owned_by_lab ? "lab owned" : "ownership unknown"}</Badge>
                </div>
                <span className="mono">{gpu.uuid}</span>
                <div className="gpu-metrics">
                  <span><small>VRAM</small>{formatBytes(gpu.vram_total_bytes)}</span>
                  <span><small>Driver</small>{gpu.driver_version ?? "unavailable"}</span>
                  <span><small>Compute</small>{gpu.compute_capability ?? "unavailable"}</span>
                  <span><small>PCI bus</small>{gpu.pci_bus_id ?? "unavailable"}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <div className="stack">
        <Panel title="Worker health" subtitle="Read-only controller state">
          <KeyValues
            items={[
              { label: "Worker ID", value: <span className="mono">{workerId}</span> },
              { label: "Status", value: <StatusBadge value={data.health.status} /> },
              { label: "Last heartbeat", value: relativeTime(data.health.last_heartbeat_at) },
              { label: "Active leases", value: data.health.active_leases?.length ? data.health.active_leases.join(", ") : "none" },
              { label: "Owned PIDs", value: data.health.owned_pids?.length ? data.health.owned_pids.join(", ") : "none" },
              { label: "Isolated", value: data.health.isolated ? "yes — inspect before resuming" : "no" },
              { label: "Snapshot digest", value: <span className="mono">{shortId(data.discovery_digest, 30)}</span> },
            ]}
          />
          {warnings.length > 0 ? (
            <ul className="warning-list">
              {warnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          ) : (
            <p className="muted">No worker warnings reported.</p>
          )}
        </Panel>

        <Panel title="Inventory coverage">
          <div className="stats-grid compact">
            <div className="stat"><span className="stat-label">Engines</span><strong className="stat-value">{data.engines?.length ?? 0}</strong></div>
            <div className="stat"><span className="stat-label">Models</span><strong className="stat-value">{data.models?.length ?? 0}</strong></div>
            <div className="stat"><span className="stat-label">GPUs</span><strong className="stat-value">{gpus.length}</strong></div>
          </div>
          <p className="muted">Only cached discovery is shown. This page does not start a scan or contact the worker.</p>
        </Panel>
      </div>
    </div>
  );
}

export function WorkersPage({ api }: PageProps) {
  const workers = usePolling(() => api.workers(), 15_000);
  const [workerId, setWorkerId] = useState<string | null>(null);

  useEffect(() => {
    if (!workerId && workers.data?.workers.length) setWorkerId(workers.data.workers[0]!.worker_id);
  }, [workerId, workers.data]);

  return (
    <>
      <PageHeader
        eyebrow="Outbound command transport"
        title="Workers"
        description="Workers pull commands; no inbound port is required. A lease or snapshot is evidence of controller state, not a guarantee of GPU health."
        actions={<button className="button button-secondary" onClick={workers.refresh}>Refresh</button>}
      />
      {workers.error ? <ErrorNotice error={workers.error} onRetry={workers.refresh} /> : null}
      {!workers.data ? <Spinner label="Loading workers" /> : null}
      {workers.data && workers.data.workers.length === 0 ? (
        <Panel><EmptyState title="No workers registered" detail="Register an enrollment token and start the worker service." /></Panel>
      ) : null}
      {workers.data && workers.data.workers.length > 0 ? (
        <div className="grid-3">
          {workers.data.workers.map((worker) => (
            <button
              key={worker.worker_id}
              className={`worker-tile ${workerId === worker.worker_id ? "selected" : ""}`}
              onClick={() => setWorkerId(worker.worker_id)}
            >
              <div className="worker-tile-top">
                <strong>{worker.name}</strong>
                <StatusBadge value={worker.status} />
              </div>
              <span className="mono">{shortId(worker.worker_id, 22)}</span>
              <span className="muted">heartbeat {relativeTime(worker.last_heartbeat_at)}</span>
              <span className="muted">snapshot rev {worker.snapshot_revision || "none"}</span>
            </button>
          ))}
        </div>
      ) : null}
      {workerId ? <WorkerDetail key={workerId} api={api} workerId={workerId} /> : null}
    </>
  );
}
