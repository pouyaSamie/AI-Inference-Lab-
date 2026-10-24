import { DataRows } from "../components/DataRows";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
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
  RefreshButton,
  EmptyState,
  ErrorNotice,
  KeyValues,
  Notice,
  Modal,
  PageHeader,
  Panel,
  SimulationBanner,
  Spinner,
  StatusBadge,
} from "../components/ui";
import type { PageProps } from "./types";

type EventConnection = "connecting" | "live" | "disconnected" | "gap";

function trialFailureSummary(kind: string): string {
  if (kind === "EXTERNAL_GPU_CONTENTION") return "Other applications are using the GPU. No performance measurement was taken. Start a new test when the GPU is quiet.";
  if (["INSUFFICIENT_VRAM", "INSUFFICIENT_RAM", "OOM"].includes(kind)) return "The test exceeded available memory. Choose a smaller model or context before starting a new test.";
  if (kind === "CANCELLED") return "This trial was cancelled before a valid measurement completed.";
  return `This trial did not produce a valid measurement: ${humanEnum(kind)}.`;
}

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
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [inspectorWidth, setInspectorWidth] = useState(320);
  const [trialFilter, setTrialFilter] = useState("");
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [connection, setConnection] = useState<EventConnection>("connecting");
  const [eventError, setEventError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const actionInFlight = useRef(false);
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
  const selectedCandidate = sortedCandidates.find(item => item.candidate_id === selectedCandidateId) ?? sortedCandidates[0];
  const selectedObservation = observations.find(item => item.candidate_id === selectedCandidate?.candidate_id);

  const act = async (name: string, action: () => Promise<unknown>) => {
    if (actionInFlight.current) return false;
    actionInFlight.current = true;
    setBusy(name);
    setActionError(null);
    try {
      await action();
      viewPoll.refresh();
      refreshShell();
      return true;
    } catch (error) {
      setActionError(error);
      return false;
    } finally {
      actionInFlight.current = false;
      setBusy(null);
    }
  };

  if (viewPoll.loading && !view) return <Spinner label="Loading experiment" />;
  if (viewPoll.error && !view) return <ErrorNotice error={viewPoll.error} onRetry={viewPoll.refresh} />;
  if (!view) return <EmptyState title="Experiment unavailable" />;

  const status = view.status;
  const active = !["completed", "failed", "cancelled", "blocked"].includes(status.state);
  const snapshot: WorkerSnapshot | null = snapshotPoll.data;
  const matches = (id: string | undefined, trial: number) => `${id ?? ""} ${trial}`.toLowerCase().includes(trialFilter.toLowerCase().trim());
  const visibleCandidates = sortedCandidates.filter(item => matches(item.candidate_id, item.trial_number));
  const visibleObservations = observations.filter(item => matches(item.candidate_id, item.trial_number));

  return (
    <>
      {cancelOpen ? <Modal title="Cancel this test?" busy={busy !== null} onClose={() => setCancelOpen(false)}>
        <p>The controller will stop this test's owned work safely. Your saved study will remain available.</p>
        <form onSubmit={event => {
          event.preventDefault();
          if (busy !== null) return;
          void act("cancel", () => api.cancel(experimentId, cancelReason.trim() || "operator cancelled from desktop UI")).then(ok => { if (ok) setCancelOpen(false); });
        }}>
          <label className="field">Reason (optional)<textarea maxLength={500} disabled={busy !== null || Boolean(viewPoll.error)} value={cancelReason} onChange={e => setCancelReason(e.target.value)} /></label>
          {actionError ? <ErrorNotice error={actionError} /> : null}
          <div className="button-row"><button type="button" className="button button-secondary" disabled={busy !== null || Boolean(viewPoll.error)} onClick={() => setCancelOpen(false)}>Keep running</button><button type="submit" className="button button-danger" disabled={busy !== null || Boolean(viewPoll.error)}>{busy === "cancel" ? "Cancelling…" : "Cancel test"}</button></div>
        </form>
      </Modal> : null}
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
            <button className="button button-secondary" disabled={busy !== null || Boolean(viewPoll.error)} onClick={() => act("pause", () => api.pause(experimentId))}>
              {busy === "pause" ? "Pausing…" : "Pause"}
            </button>
          ) : null}
          {status.state === "paused" ? (
            <button className="button button-primary" disabled={busy !== null || Boolean(viewPoll.error)} onClick={() => act("resume", () => api.resume(experimentId))}>
              {busy === "resume" ? "Resuming…" : "Resume"}
            </button>
          ) : null}
          {status.state === "blocked" && status.stage === "preflight" ? (
            <button className="button button-secondary" disabled={busy !== null || Boolean(viewPoll.error)} onClick={() => act("retry", () => api.retryPreflight(experimentId))}>
              {busy === "retry" ? "Queueing…" : "Retry preflight"}
            </button>
          ) : null}
          {active ? (
            <button
              className="button button-danger"
              disabled={busy !== null || Boolean(viewPoll.error)}
              onClick={() => {
                setActionError(null); setCancelReason(""); setCancelOpen(true);
              }}
            >
              {busy === "cancel" ? "Cancelling…" : "Cancel"}
            </button>
          ) : null}
        </div>
      </div>

      {viewPoll.error ? <Notice tone="warn" title="Last known run state — refresh failed">
        Last successful response: {formatTimestamp(viewPoll.lastSuccessAt)}. This connection error does not indicate a failed or stopped run. Controls are disabled until a fresh response arrives.
        <ErrorNotice error={viewPoll.error} onRetry={viewPoll.refresh} />
      </Notice> : null}
      <SimulationBanner simulated={view.simulation ?? false} warnings={view.warnings ?? []} />
      {status.state === "completed" && observations.length > 0 && observations.every(item => !["measured", "screening_only", "simulated"].includes(item.measurement_status)) ? (
        <Notice tone="warn" title="Finished without valid measurements">The study is saved, but usable measurements are missing. Completed means processing finished; this is not a successful benchmark. See the trial reasons below.</Notice>
      ) : null}
      {actionError ? <ErrorNotice error={actionError} /> : null}
      {eventError ? (
        <Notice tone="warn" title="Event stream needs resync">
          <p>{eventError instanceof Error ? eventError.message : "The event stream disconnected."}</p>
          <RefreshButton label="Refresh run snapshot" onClick={() => { viewPoll.refresh(); setEventError(null); }} />
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
        {snapshotPoll.error ? <Notice tone="warn" title="Worker snapshot refresh unavailable">Cached hardware may be stale. No live telemetry is inferred.</Notice> : null}
        {snapshot ? (
          <p className="muted">
            Worker telemetry: {snapshot.hardware.gpus?.map((gpu) => `${gpu.name} (${formatBytes(gpu.vram_total_bytes)} VRAM)`).join(", ") || "no GPU reported"}.
            Cached snapshots do not include live utilization; the UI does not invent it.
          </p>
        ) : null}
      </Panel>

      <div className="evidence-toolbar">
        <label className="field-inline">Find trial<input type="search" placeholder="Trial number or candidate ID" value={trialFilter} onChange={event => setTrialFilter(event.target.value)} /></label>
        <button className="button button-secondary" aria-expanded={inspectorOpen} aria-controls="trial-inspector" onClick={() => setInspectorOpen(!inspectorOpen)}>{inspectorOpen ? "Hide inspector" : "Show inspector"}</button>
        {inspectorOpen ? <label className="inspector-size">Inspector width<input type="range" min={280} max={420} step={20} value={inspectorWidth} aria-valuetext={`${inspectorWidth} pixels`} onChange={event => setInspectorWidth(Number(event.target.value))} /></label> : null}
      </div>
      <div className={`run-workspace ${inspectorOpen ? "" : "inspector-closed"}`} style={{"--inspector-width": `${inspectorWidth}px`} as CSSProperties}>
      <div className="run-trials">
      <div className="grid-2 run-evidence-grid">
        <Panel title="Candidates" subtitle="Parameters come from the immutable candidate records.">
          {visibleCandidates.length === 0 ? (
            <EmptyState title={trialFilter ? "No matching candidates" : "No candidates yet"} detail={trialFilter ? "Clear the trial filter to see all retained candidates." : "The optimizer asks for a paired baseline before TPE candidates."} />
          ) : (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table">
              <table>
                <thead><tr><th scope="col">Trial</th><th scope="col">Role</th><th scope="col">Context</th><th scope="col">State</th><th scope="col">Parameters</th></tr></thead>
                <DataRows items={visibleCandidates} columns={5} label="candidates" getOrder={item => item.trial_number}>{(candidate) => (
                    <tr key={candidate.candidate_id} className={candidate.candidate_id === selectedCandidate?.candidate_id ? "selected" : ""}>
                      <td><button className="link-button" aria-pressed={candidate.candidate_id === selectedCandidate?.candidate_id} onClick={() => { setSelectedCandidateId(candidate.candidate_id ?? null); setInspectorOpen(true); }}>Trial {candidate.trial_number}</button></td>
                      <td><Badge tone={candidate.role === "baseline" ? "info" : "neutral"}>{candidate.role ?? "candidate"}</Badge></td>
                      <td>{CONTEXT_LABELS[candidate.context]}</td>
                      <td><StatusBadge value={observations.find(item => item.candidate_id === candidate.candidate_id)?.status ?? candidate.state} /></td>
                      <td><details><summary>View parameters</summary><pre className="mono wrap small">{JSON.stringify(candidate.parameters, null, 2)}</pre></details></td>
                    </tr>
                  )}</DataRows>
              </table>
            </div>
          )}
        </Panel>

        <Panel title="Retained samples" subtitle="Finalization uses paired primary-level samples, not just averages.">
          {observations.filter(item => item.failure || item.measurement_status === "unavailable").length > 10 ? <p className="muted">Showing up to 10 notices per failure type. Every retained trial remains available in the paged table and inspector.</p> : null}
          {observations.filter(item => item.failure).slice(0, 10).map(item => <Notice key={item.observation_id} tone="warn" title={`Trial ${item.trial_number} did not complete`}>
            <p>{trialFailureSummary(item.failure!.kind)}</p>
            <details><summary>Failure code</summary><code>{item.failure!.kind}</code>{item.failure!.process_exit_code != null ? <p>Process exit: {item.failure!.process_exit_code}</p> : null}</details>
          </Notice>)}
          {observations.filter(item => !item.failure && item.measurement_status === "unavailable").slice(0, 10).map(item => <Notice key={`unavailable-${item.observation_id}`} tone="warn" title={`Trial ${item.trial_number}: measurements unavailable`}>
            <p>The engine finished, but it did not return the answer text or timing data needed to measure performance. This trial cannot qualify a recipe.</p>
          </Notice>)}
          {visibleObservations.length === 0 ? (
            <EmptyState title={trialFilter ? "No matching observations" : "No observations"} detail="Observations appear after a candidate completes its workload. Clear filters to see all retained records." />
          ) : (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table">
              <table>
                <thead><tr><th scope="col">Trial</th><th scope="col">Evidence</th><th scope="col" className="numeric">Prefill</th><th scope="col" className="numeric">Decode</th><th scope="col" className="numeric">TTFT</th><th scope="col" className="numeric">VRAM</th><th scope="col" className="numeric">Samples</th></tr></thead>
                <DataRows items={visibleObservations} columns={7} label="observations" getOrder={item => item.trial_number}>{(observation) => (
                    <tr key={observation.observation_id}>
                      <td>{observation.trial_number}</td>
                      <td>
                        <Badge tone={observation.simulated ? "simulated" : "info"}>{observation.evidence_kind}</Badge>
                        <small>{observation.measurement_status}</small>{observation.failure ? <small>{observation.failure.kind}</small> : null}
                      </td>
                      <td className="numeric">{metric(observation.metrics?.prefill_tokens_per_sec, " tok/s")}</td>
                      <td className="numeric">{metric(observation.metrics?.decode_tokens_per_sec, " tok/s")}</td>
                      <td className="numeric">{metric(observation.metrics?.time_to_first_token_ms, " ms")}</td>
                      <td className="numeric">{formatBytes(observation.metrics?.gpu_vram_peak_bytes)}</td>
                      <td className="numeric">{observation.samples?.length ?? 0}</td>
                    </tr>
                  )}</DataRows>
              </table>
            </div>
          )}
        </Panel>
      </div>

      </div>
      {inspectorOpen ? <aside id="trial-inspector" className="trial-inspector" aria-label="Selected trial inspector">
        <Panel title={selectedCandidate ? `Trial ${selectedCandidate.trial_number}` : "Trial inspector"} subtitle="Immutable controller evidence">
          {selectedCandidate ? <>
            <StatusBadge value={selectedObservation?.status ?? selectedCandidate.state} />
            <KeyValues items={[
              { label: "Candidate", value: <code>{selectedCandidate.candidate_id}</code> },
              { label: "Context", value: `${CONTEXT_LABELS[selectedCandidate.context]} tokens` },
              { label: "Role", value: selectedCandidate.role ?? "candidate" },
              { label: "Measurement", value: selectedObservation?.measurement_status ?? "No observation" },
              { label: "Prefill", value: metric(selectedObservation?.metrics?.prefill_tokens_per_sec, " tok/s") },
              { label: "Decode", value: metric(selectedObservation?.metrics?.decode_tokens_per_sec, " tok/s") },
              { label: "TTFT", value: metric(selectedObservation?.metrics?.time_to_first_token_ms, " ms") },
              { label: "Peak VRAM", value: formatBytes(selectedObservation?.metrics?.gpu_vram_peak_bytes) },
            ]} />
            {selectedObservation?.failure ? <Notice tone="warn" title={selectedObservation.failure.kind}>{trialFailureSummary(selectedObservation.failure.kind)}</Notice> : null}
            <h3 className="subsection-title">Effective parameters</h3>
            <pre className="mono">{JSON.stringify(selectedCandidate.parameters, null, 2)}</pre>
            <p className="muted">{view.simulation ? "Simulated fixture evidence. Cannot qualify a recipe." : "Retained observation summary. Qualification requires paired samples and guardrails."}</p>
          </> : <EmptyState title="Awaiting candidates" detail="Select a trial when controller records are available." />}
        </Panel>
      </aside> : null}
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
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table">
              <table>
                <thead><tr><th scope="col">Context</th><th scope="col">Status</th><th scope="col">Estimated VRAM</th><th scope="col">Reason</th></tr></thead>
                <tbody>
                  {view.feasibility.map((item) => (
                    <tr key={item.context}>
                      <td>{CONTEXT_LABELS[item.context]}</td>
                      <td><StatusBadge value={item.status} /></td>
                      <td className="numeric">{formatBytes(item.estimated_vram_bytes)}</td>
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
        description="Stage, trials and event history are retained by the controller. Minimize to keep desktop-managed local work running; Quit stops the local lab. Independent services continue separately."
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
            title={experimentsError ? "Run history unavailable" : "No experiments"}
            detail={experimentsError ? "Reconnect to retrieve controller records. This connection error does not indicate that any run failed or stopped." : "Create an immutable experiment from Optimize. The UI never starts a benchmark directly."}
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
