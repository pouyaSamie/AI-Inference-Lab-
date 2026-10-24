import { usePolling } from "../lib/hooks";
import { formatBytes, relativeTime, shortId } from "../lib/format";
import { PageHeader, Panel, Stat, StatusBadge, Badge, EmptyState, ErrorNotice, Spinner } from "../components/ui";
import type { PageProps } from "./types";

export function OverviewPage({
  api,
  status,
  statusError,
  experiments,
  experimentsError,
  navigate,
  refreshShell,
}: PageProps) {
  const workers = usePolling(() => api.workers(), 15_000);
  const recipes = usePolling(() => api.recipes(), 20_000);

  const active = experiments?.experiments.filter((item) =>
    ["queued", "preflight_required", "preflighting", "ready", "running", "paused", "cancelling"].includes(
      item.state,
    ),
  );
  const recent = experiments?.experiments.slice(0, 6) ?? [];
  const workerList = workers.data?.workers ?? [];

  return (
    <>
      <PageHeader
        eyebrow="Operator overview"
        title="Lab at a glance"
        description="Controller, worker and optimizer health with the latest immutable studies. Minimize to keep desktop-managed local work running; independent services have their own lifecycle."
        actions={
          <>
            <button className="button button-secondary" onClick={() => navigate("help")}>
              Getting started
            </button>
            <button className="button button-secondary" onClick={() => navigate("workers")}>
              Inspect workers
            </button>
            <button className="button button-primary" onClick={() => navigate("optimize")}>
              New optimization
            </button>
          </>
        }
      />

      <Panel title="Your next step" subtitle="Choose a model, test a configuration, then inspect the measured result.">
        <ol className="journey-steps">
          <li><strong>1. Prepare</strong><p>Add model folders and select one installed engine build. Verification can take time for large files.</p><button className="button button-secondary" onClick={() => navigate("settings")}>Set up engines & models</button></li>
          <li><strong>2. Optimize</strong><p>Choose a verified model, engine, objective and context sizes. Review preflight before submitting.</p><button className="button button-primary" onClick={() => navigate("optimize")}>Plan an optimization</button></li>
          <li><strong>3. Review</strong><p>Follow the run, compare it with its paired baseline, and save a recipe only if it qualifies.</p><button className="button button-secondary" onClick={() => navigate(active?.length ? "live" : "compare")}>{active?.length ? "Follow active runs" : "Compare results"}</button></li>
        </ol>
      </Panel>

      {statusError ? <ErrorNotice error={statusError} onRetry={refreshShell} /> : null}
      {experimentsError ? <ErrorNotice error={experimentsError} onRetry={refreshShell} /> : null}

      <div className="stats-grid">
        <Stat
          label="Workers online"
          value={status?.workers_online ?? workers.data?.workers.filter((w) => w.status === "online").length ?? "—"}
          detail={workerList.length ? `${workerList.length} registered` : "No inventory yet"}
          tone={status?.workers_online ? "ok" : "warn"}
        />
        <Stat
          label="Active jobs"
          value={status?.experiments_active ?? active?.length ?? "—"}
          detail="Durable controller jobs"
          tone={active?.length ? "info" : "neutral"}
        />
        <Stat
          label="Optimizer"
          value={!status ? "Unknown" : status.optimizer?.online ? "Online" : "Offline"}
          detail={status?.optimizer?.studies_open ? `${status.optimizer.studies_open} open studies` : "Separate Optuna process"}
          tone={status?.optimizer?.online ? "ok" : "danger"}
        />
        <Stat
          label="Scheduler"
          value={!status ? "Unknown" : status.scheduler_running ? "Running" : "Stopped"}
          detail={!status ? "Controller policy unavailable" : status.allow_simulation ? "Simulation allowed by controller policy" : "Real evidence only"}
          tone={status?.scheduler_running ? "ok" : "danger"}
        />
      </div>

      <div className="grid-2">
        <Panel
          title="Workers"
          subtitle="Cached inventory; refresh only reads controller snapshots."
        >
          {workers.error ? <ErrorNotice error={workers.error} onRetry={workers.refresh} /> : null}
          {!workers.data ? !workers.error ? <Spinner label="Loading workers" /> : null : workerList.length === 0 ? (
            <EmptyState
              title="No workers registered"
              detail="Select model and engine paths in Settings. The installed app starts its local worker automatically."
            />
          ) : (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Worker</th>
                    <th scope="col">Status</th>
                    <th scope="col">Heartbeat</th>
                    <th scope="col">GPU / VRAM</th>
                    <th scope="col">Snapshot</th>
                  </tr>
                </thead>
                <tbody>
                  {workerList.map((worker) => (
                    <tr key={worker.worker_id}>
                      <td>
                        <strong>{worker.name}</strong>
                        <small>{shortId(worker.worker_id, 18)}</small>
                      </td>
                      <td><StatusBadge value={worker.status} /></td>
                      <td>{relativeTime(worker.last_heartbeat_at)}</td>
                      <td>
                        {worker.gpus?.length
                          ? worker.gpus.map((gpu) => {
                              const typed = gpu as { name?: string; vram_total_bytes?: number };
                              return (
                                <span key={`${worker.worker_id}-${typed.name}`} className="stack-line">
                                  <strong>{typed.name ?? "GPU"}</strong>
                                  <small>{formatBytes(typed.vram_total_bytes)}</small>
                                </span>
                              );
                            })
                          : "unavailable"}
                      </td>
                      <td>
                        <Badge tone={worker.snapshot_revision > 0 ? "info" : "warn"}>
                          rev {worker.snapshot_revision || "none"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel
          title="Active jobs"
          subtitle="Stage progress is controller state, not a wall-clock promise."
          actions={<button className="link-button" onClick={() => navigate("live")}>Open live runs</button>}
        >
          {!experiments ? !experimentsError ? <Spinner label="Loading active jobs" /> : <EmptyState title="Active job state unavailable" detail="Reconnect to retrieve durable controller state." /> : !active || active.length === 0 ? (
            <EmptyState title="No active jobs" detail="Submit a plan from Optimize to start a durable study." />
          ) : (
            <div className="job-list">
              {active.map((job) => (
                <button key={job.experiment_id} className="job-card" onClick={() => navigate("live", job.experiment_id)}>
                  <div className="job-card-top">
                    <strong>{job.model_id}</strong>
                    <StatusBadge value={job.state} />
                  </div>
                  <div className="job-card-meta">
                    <span>{job.engine_id}</span>
                    <span>{job.objective}</span>
                    <span>stage: {job.stage.replaceAll("_", " ")}</span>
                  </div>
                  <div className="job-card-meta">
                    <span>candidates {job.counters?.candidates_completed ?? 0}/{job.counters?.candidates_proposed ?? 0}</span>
                    <span>{job.counters?.observations_committed ?? 0} observations</span>
                    <span>rev {job.revision}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <div className="grid-2">
        <Panel
          title="Recent experiments"
          subtitle="Open any run to replay its event stream and inspect evidence."
        >
          {!experiments ? !experimentsError ? <Spinner label="Loading experiment history" /> : null : recent.length === 0 ? (
            <EmptyState title="No experiments" detail="The controller has not persisted an experiment yet." />
          ) : (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Job</th>
                    <th scope="col">State</th>
                    <th scope="col">Engine</th>
                    <th scope="col">Contexts</th>
                    <th scope="col">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map((job) => (
                    <tr key={job.experiment_id} className="clickable" onClick={() => navigate("live", job.experiment_id)}>
                      <td>
                        <button className="link-button" onClick={() => navigate("live", job.experiment_id)}>{job.model_id}</button>
                        <small>{shortId(job.experiment_id, 20)}</small>
                      </td>
                      <td><StatusBadge value={job.state} /></td>
                      <td>{job.engine_id}</td>
                      <td>{job.contexts.map((value) => `${value / 1024}K`).join(", ") || "—"}</td>
                      <td>{relativeTime(job.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel title="Recipes" subtitle="Only measured, paired, qualified evidence becomes a validated recipe.">
          {recipes.error ? <ErrorNotice error={recipes.error} onRetry={recipes.refresh} /> : null}
          {!recipes.data ? !recipes.error ? <Spinner label="Loading recipes" /> : null : recipes.data.recipes.length === 0 ? (
            <EmptyState
              title="No recipes"
              detail="Simulated or inconclusive evidence never becomes a recipe. Complete a real paired baseline/candidate run first."
            />
          ) : (
            <div className="recipe-list">
              {recipes.data.recipes.slice(0, 4).map((recipe) => (
                <button key={recipe.recipe_id} className="recipe-row" onClick={() => navigate("recipes", recipe.experiment_id)}>
                  <div>
                    <strong>{recipe.recipe_id}</strong>
                    <small>{shortId(recipe.recipe_digest, 22)}</small>
                  </div>
                  <Badge tone={recipe.status === "validated" ? "ok" : "warn"}>{recipe.status}</Badge>
                </button>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {(status?.warnings?.length ?? 0) > 0 ? (
        <Panel title="Controller warnings">
          <ul className="warning-list">
            {status?.warnings?.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        </Panel>
      ) : null}
    </>
  );
}
