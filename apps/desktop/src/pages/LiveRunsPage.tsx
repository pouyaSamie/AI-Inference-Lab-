import { useEffect, useMemo, useRef, useState } from "react";
import type { ExperimentView, JobEvent, WorkerSnapshot } from "../lib/contracts";
import { CONTEXT_LABELS, STAGES } from "../lib/contracts";
import type { EventPage } from "../lib/contracts";
import { usePolling } from "../lib/hooks";
import {
  formatBytes,
  formatTimestamp,
  humanEnum,
  metric,
  relativeTime,
  shortId,
} from "../lib/format";
import {
  Badge,
  EmptyState,
  ErrorNotice,
  KeyValues,
  Notice,
  PageHeader,
  Panel,
  SimulationBanner,
  Spinner,
  StatusBadge,
} from "../components/ui";
import type { PageProps } from "./types";

type EventConnection = "connecting" | "live" | "disconnected" | "gap";

function mergeEvent(current: JobEvent[], next: JobEvent): JobEvent[] {
  if (current.some((event) => event.event_id === next.event_id)) return current;
  return [...current, next].sort((a, b) => a.sequence - b.sequence).slice(-250);
}

function parseSnapshotEvents(data: unknown): JobEvent[] {
  if (typeof data !== "object" || data === null) return [];
  const snapshot = (data as { snapshot?: unknown }).snapshot;
  if (typeof snapshot !== "object" || snapshot === null) return [];
  const recent = (snapshot as { recent_events?: unknown }).recent_events;
  if (!Array.isArray(recent)) return [];
  return recent.filter((item): item is JobEvent => {
    return (
      typeof item === "object" &&
      item !== null &&
      "event_id" in item &&
      "sequence" in item &&
      "type" in item
    );
  });
}

function EventsTable({ events }: { events: JobEvent[] }) {
  if (events.length === 0) {
    return <EmptyState title="No events yet" detail="The controller will append durable events as the job progresses." />;
  }
  return (
    <div className="event-list">
      {events
        .slice()
        .reverse()
        .map((event) => (
          <details key={event.event_id} className="event-row">
            <summary>
              <span className="event-seq">#{event.sequence}</span>
              <strong>{event.type}</strong>
              {event.stage ? <Badge tone="neutral">{humanEnum(event.stage)}</Badge> : null}
              {event.state ? <StatusBadge value={event.state} /> : null}
              <span className="event-time">{relativeTime(event.created_at)}</span>
            </summary>
            <div className="event-payload">
              <span className="mono">{event.event_id}</span>
              <pre>{JSON.stringify(event.payload ?? {}, null, 2)}</pre>
            </div>
          </details>
        ))}
      </div>
  );
}

function StageTimeline({ view }: { view: ExperimentView }) {
  const terminal = ["completed", "failed", "cancelled"].includes(view.status.state);
  const currentIndex = STAGES.indexOf(view.status.stage);
  return (
    <ol className="stage-timeline">
      {STAGES.map((stage, index) => {
        const done = terminal ? view.status.state === "completed" : index < currentIndex;
        const active = index === currentIndex && !terminal;
        return (
          <li
            key={stage}
            className={`${done ? "done" : ""} ${active ? "active" : ""} ${
              terminal && index === currentIndex && view.status.state !== "completed" ? "failed" : ""
            }`}
          >
            <span className="stage-dot" />
            <span>{humanEnum(stage)}</span>
          </li>
        );
      })}
    </ol>
  );
}

function ResultsSummary({
  api,
  experimentId,
  onOpenCompare,
}: {
  api: PageProps["api"];
  experimentId: string;
  onOpenCompare: () => void;
}) {
  const results = usePolling(() => api.results(experimentId), 30_000);
  if (results.error) return <ErrorNotice error={results.error} onRetry={results.refresh} />;
  if (!results.data) return <Spinner label="Loading finalization" />;
  const finalization = results.data.finalization;
  return (
    <Panel
      title="Finalization"
      subtitle="Cross-context aggregation is only complete when every selected context has evidence."
      actions={<button className="link-button" onClick={onOpenCompare}>Open comparison</button>}
    >
      <SimulationBanner simulated={finalization.simulated ?? results.data.simulated ?? false} warnings={results.data.warnings ?? []} />
      <div className="stats-grid compact">
        <div className="stat">
          <span className="stat-label">Classification</span>
          <strong className="stat-value"><StatusBadge value={finalization.classification} /></strong>
        </div>
        <div className="stat">
          <span className="stat-label">Validated winner</span>
          <strong className="stat-value mono">{finalization.validated_winner_candidate_id ?? "none"}</strong>
        </div>
        <div className="stat">
          <span className="stat-label">Gate</span>
          <strong className="stat-value">≥{finalization.threshold_pct ?? 5}% · {Math.round((finalization.confidence_level ?? 0.95) * 100)}%</strong>
        </div>
        <div className="stat">
          <span className="stat-label">Recipe mode</span>
          <strong className="stat-value">{humanEnum(finalization.recipe_mode)}</strong>
        </div>
      </div>
      {finalization.validated_winner_candidate_id ? (
        <Notice tone="ok" title="Validated winner available">
          The candidate passed the paired improvement gate in every required context. Create its recipe from the Recipes
          page; promotion is a separate explicit operator action.
        </Notice>
      ) : (
        <Notice tone="warn" title="No validated winner">
          No candidate qualified. Highest throughput is never a winner by itself. Inspect per-context paired intervals
          and reasons in Compare.
        </Notice>
      )}
    </Panel>
  );
}

function RunDetail({
  api,
  experimentId,
  navigate,
  refreshShell,
}: {
  api: PageProps["api"];
  experimentId: string;
  navigate: PageProps["navigate"];
  refreshShell: () => void;
}) {
  const viewPoll = usePolling(() => api.experiment(experimentId), 6_000);
  const snapshotPoll = usePolling(async () => {
    const workerId = viewPoll.data?.status.worker_id;
    if (!workerId) return null;
    return api.workerSnapshot(workerId);
  }, 20_000);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [connection, setConnection] = useState<EventConnection>("connecting");
  const [eventError, setEventError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const lastEventId = useRef(0);
  const view = viewPoll.data;

  useEffect(() => {
    let stopped = false;
    lastEventId.current = view?.status.last_event_id ?? 0;
    setEvents([]);
    setEventError(null);
    setConnection("connecting");
    void api
      .eventPage(experimentId, 0, 100)
      .then((page: EventPage) => {
        if (stopped) return;
        setEvents(page.events.slice(-250));
        lastEventId.current = Math.max(
          lastEventId.current,
          page.last_event_id,
          ...page.events.map((event) => event.sequence),
        );
      })
      .catch((error: unknown) => {
        if (!stopped) setEventError(error);
      });

    const stop = api.subscribeEvents(experimentId, lastEventId.current, (event, id, data) => {
      if (stopped) return;
      if (id !== null) lastEventId.current = Math.max(lastEventId.current, id);
      if (event === "transport.error") {
        setConnection("disconnected");
        setEventError(data);
        return;
      }
      if (event === "event.gap") {
        setConnection("gap");
        viewPoll.refresh();
        return;
      }
      setConnection("live");
      if (event === "snapshot") {
        for (const item of parseSnapshotEvents(data)) {
          setEvents((current) => mergeEvent(current, item));
        }
        return;
      }
      if (typeof data === "object" && data !== null && "event_id" in data && "sequence" in data) {
        setEvents((current) => mergeEvent(current, data as JobEvent));
      }
    });

    return () => {
      stopped = true;
      stop();
    };
    // The view's last event id is only a seed; polling updates must not restart the stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, experimentId]);

  const sortedCandidates = useMemo(() => view?.candidates ?? [], [view?.candidates]);
  const observations = view?.observations ?? [];

  const act = async (name: string, action: () => Promise<unknown>) => {
    setBusy(name);
    setActionError(null);
    try {
      await action();
      viewPoll.refresh();
      refreshShell();
    } catch (error) {
      setActionError(error);
    } finally {
      setBusy(null);
    }
  };

  if (viewPoll.loading && !view) return <Spinner label="Loading experiment" />;
  if (viewPoll.error) return <ErrorNotice error={viewPoll.error} onRetry={viewPoll.refresh} />;
  if (!view) return <EmptyState title="Experiment unavailable" />;

  const status = view.status;
  const active = !["completed", "failed", "cancelled", "blocked"].includes(status.state);
  const snapshot: WorkerSnapshot | null = snapshotPoll.data;

  return (
    <>
      <div className="run-heading">
        <div>
          <span className="eyebrow">{shortId(status.experiment_id, 28)}</span>
          <h1>{view.spec.model.display_name}</h1>
          <p className="page-description">
            {view.spec.engine.engine_id} · {view.spec.engine.version} · {status.objective} ·{" "}
            {view.spec.contexts.map((context) => CONTEXT_LABELS[context]).join(", ")}
          </p>
        </div>
        <div className="run-actions">
          <StatusBadge value={status.state} />
          <Badge tone={status.paused ? "warn" : "info"}>{status.paused ? "Paused" : "Scheduler owned"}</Badge>
          {status.state === "running" ? (
            <button className="button button-secondary" disabled={busy !== null} onClick={() => act("pause", () => api.pause(experimentId))}>
              {busy === "pause" ? "Pausing…" : "Pause"}
            </button>
          ) : null}
          {status.state === "paused" ? (
            <button className="button button-primary" disabled={busy !== null} onClick={() => act("resume", () => api.resume(experimentId))}>
              {busy === "resume" ? "Resuming…" : "Resume"}
            </button>
          ) : null}
          {status.state === "preflight_required" ? (
            <button className="button button-secondary" disabled={busy !== null} onClick={() => act("retry", () => api.retryPreflight(experimentId))}>
              {busy === "retry" ? "Queueing…" : "Retry preflight"}
            </button>
          ) : null}
          {active ? (
            <button
              className="button button-danger"
              disabled={busy !== null}
              onClick={() => {
                const reason = window.prompt("Cancellation reason (stored in the audit trail):", "operator cancelled from desktop UI");
                if (reason) void act("cancel", () => api.cancel(experimentId, reason));
              }}
            >
              {busy === "cancel" ? "Cancelling…" : "Cancel"}
            </button>
          ) : null}
        </div>
      </div>

      <SimulationBanner simulated={view.simulation ?? false} warnings={view.warnings ?? []} />
      {actionError ? <ErrorNotice error={actionError} /> : null}
      {eventError ? (
        <Notice tone="warn" title="Event stream needs resync">
          <p>{eventError instanceof Error ? eventError.message : "The event stream disconnected."}</p>
          <button className="link-button" onClick={() => { viewPoll.refresh(); setEventError(null); }}>Refresh snapshot</button>
        </Notice>
      ) : null}
      {connection === "gap" ? (
        <Notice tone="warn" title="Event replay gap">
          The controller could not replay every event. The page refreshed the snapshot; event history may be incomplete.
        </Notice>
      ) : null}

      <Panel
        title="Stage timeline"
        subtitle={`Revision ${status.revision} · last event ${status.last_event_id ?? 0} · updated ${relativeTime(status.updated_at)}`}
        actions={
          <span className={`stream-state stream-${connection}`}>
            <span className="connection-dot" aria-hidden="true" />
            {connection === "live" ? "SSE live" : connection === "gap" ? "SSE gap" : connection === "disconnected" ? "SSE offline" : "SSE connecting"}
          </span>
        }
      >
        <StageTimeline view={view} />
        <div className="stats-grid compact">
          <div className="stat"><span className="stat-label">Candidates</span><strong className="stat-value">{status.counters?.candidates_completed ?? 0} / {status.counters?.candidates_proposed ?? 0}</strong><span className="stat-detail">{status.counters?.candidates_failed ?? 0} failed</span></div>
          <div className="stat"><span className="stat-label">Observations</span><strong className="stat-value">{status.counters?.observations_committed ?? 0}</strong><span className="stat-detail">{status.counters?.trials_finalized ?? 0} trials finalized</span></div>
          <div className="stat"><span className="stat-label">Work units</span><strong className="stat-value">{status.counters?.work_units_done ?? 0} / {status.counters?.work_units_total ?? "?"}</strong></div>
          <div className="stat"><span className="stat-label">Plan digest</span><strong className="stat-value mono">{shortId(status.plan_digest, 16)}</strong></div>
        </div>
        {status.error_message ? (
          <Notice tone="danger" title={status.error_code ?? "Experiment error"}>{status.error_message}</Notice>
        ) : null}
        {snapshot ? (
          <p className="muted">
            Worker telemetry: {snapshot.hardware.gpus?.map((gpu) => `${gpu.name} (${formatBytes(gpu.vram_total_bytes)} VRAM)`).join(", ") || "no GPU reported"}.
            Cached snapshots do not include live utilization; the UI does not invent it.
          </p>
        ) : null}
      </Panel>

      <div className="grid-2">
        <Panel title="Candidates" subtitle="Parameters come from the immutable candidate records.">
          {sortedCandidates.length === 0 ? (
            <EmptyState title="No candidates yet" detail="The optimizer asks for a paired baseline before TPE candidates." />
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Trial</th><th>Role</th><th>Context</th><th>State</th><th>Parameters</th></tr></thead>
                <tbody>
                  {sortedCandidates.map((candidate) => (
                    <tr key={candidate.candidate_id}>
                      <td>{candidate.trial_number}</td>
                      <td><Badge tone={candidate.role === "baseline" ? "info" : "neutral"}>{candidate.role ?? "candidate"}</Badge></td>
                      <td>{CONTEXT_LABELS[candidate.context]}</td>
                      <td><StatusBadge value={candidate.state} /></td>
                      <td><span className="mono wrap small">{JSON.stringify(candidate.parameters)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel title="Retained samples" subtitle="Finalization uses paired primary-level samples, not just averages.">
          {observations.length === 0 ? (
            <EmptyState title="No observations" detail="Observations appear after a candidate completes its workload." />
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Trial</th><th>Evidence</th><th>Prefill</th><th>Decode</th><th>TTFT</th><th>VRAM</th><th>Samples</th></tr></thead>
                <tbody>
                  {observations.map((observation) => (
                    <tr key={observation.observation_id}>
                      <td>{observation.trial_number}</td>
                      <td>
                        <Badge tone={observation.simulated ? "simulated" : "info"}>{observation.evidence_kind}</Badge>
                        <small>{observation.measurement_status}</small>
                      </td>
                      <td>{metric(observation.metrics?.prefill_tokens_per_sec, " tok/s")}</td>
                      <td>{metric(observation.metrics?.decode_tokens_per_sec, " tok/s")}</td>
                      <td>{metric(observation.metrics?.time_to_first_token_ms, " ms")}</td>
                      <td>{formatBytes(observation.metrics?.gpu_vram_peak_bytes)}</td>
                      <td>{observation.samples?.length ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      {["completed", "failed", "cancelled"].includes(status.state) ? (
        <ResultsSummary api={api} experimentId={experimentId} onOpenCompare={() => navigate("compare", experimentId)} />
      ) : null}

      <div className="grid-2">
        <Panel title="Durable event timeline" subtitle="Replay-safe sequence numbers from the controller event log.">
          <EventsTable events={events} />
        </Panel>
        <Panel title="Run details" subtitle="IDs and hashes are copyable evidence references.">
          <KeyValues
            items={[
              { label: "Experiment", value: <span className="mono wrap">{status.experiment_id}</span> },
              { label: "Worker", value: status.worker_id },
              { label: "Engine", value: `${view.spec.engine.engine_id} · ${view.spec.engine.version}` },
              { label: "Model", value: view.spec.model.model_id },
              { label: "Spec digest", value: <span className="mono wrap">{status.spec_digest}</span> },
              { label: "Plan", value: <span className="mono wrap">{view.plan.plan_id}</span> },
              { label: "Created", value: formatTimestamp(view.created_at) },
              { label: "Completed", value: view.completed_at ? formatTimestamp(view.completed_at) : "not finished" },
              { label: "Simulation", value: view.simulation ? "explicit simulation lane" : "real lane" },
              { label: "Recipe mode", value: humanEnum(view.spec.recipe_mode ?? "per_context") },
            ]}
          />
          <h3 className="subsection-title">Feasibility</h3>
          {view.feasibility?.length ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Context</th><th>Status</th><th>Estimated VRAM</th><th>Reason</th></tr></thead>
                <tbody>
                  {view.feasibility.map((item) => (
                    <tr key={item.context}>
                      <td>{CONTEXT_LABELS[item.context]}</td>
                      <td><StatusBadge value={item.status} /></td>
                      <td>{formatBytes(item.estimated_vram_bytes)}</td>
                      <td>{item.reason ?? item.evidence?.[0] ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="muted">No feasibility report recorded.</p>}
          <p className="muted">
            Sanitized logs remain worker-owned. This UI shows controller events and observation facts; it does not expose
            arbitrary filesystem paths or environment dumps.
          </p>
        </Panel>
      </div>
    </>
  );
}

export function LiveRunsPage({
  api,
  experiments,
  experimentsError,
  activeExperimentId,
  setActiveExperimentId,
  navigate,
  refreshShell,
}: PageProps) {
  const list = experiments?.experiments ?? [];
  const selected = activeExperimentId ?? list[0]?.experiment_id ?? null;

  useEffect(() => {
    if (!activeExperimentId && list.length > 0) setActiveExperimentId(list[0]!.experiment_id);
  }, [activeExperimentId, list, setActiveExperimentId]);

  return (
    <>
      <PageHeader
        eyebrow="Independent execution"
        title="Live Runs"
        description="Stage, trial, telemetry and event history live in the controller. This view can reconnect or close without affecting the job."
        actions={
          <label className="field-inline">
            <span>Experiment</span>
            <select value={selected ?? ""} onChange={(event) => setActiveExperimentId(event.target.value || null)}>
              <option value="">Select</option>
              {list.map((job) => (
                <option key={job.experiment_id} value={job.experiment_id}>
                  {job.model_id} · {job.state} · {shortId(job.experiment_id, 12)}
                </option>
              ))}
            </select>
          </label>
        }
      />
      {experimentsError ? <ErrorNotice error={experimentsError} onRetry={refreshShell} /> : null}
      {list.length === 0 ? (
        <Panel>
          <EmptyState
            title="No experiments"
            detail="Create an immutable experiment from Optimize. The UI never starts a benchmark directly."
            action={<button className="button button-primary" onClick={() => navigate("optimize")}>Open Optimize</button>}
          />
        </Panel>
      ) : selected ? (
        <RunDetail key={selected} api={api} experimentId={selected} navigate={navigate} refreshShell={refreshShell} />
      ) : (
        <Panel><EmptyState title="Select an experiment" /></Panel>
      )}
    </>
  );
}
