import { useEffect, useMemo, useState } from "react";
import type {
  BenchmarkObservation,
  CandidateSpec,
  ContextEvaluation,
  ExperimentResultsResponse,
} from "../lib/contracts";
import { CONTEXTS, CONTEXT_LABELS } from "../lib/contracts";
import { usePolling } from "../lib/hooks";
import {
  formatBytes,
  formatDelta,
  metric,
  shortId,
} from "../lib/format";
import {
  Badge,
  EmptyState,
  ErrorNotice,
  PageHeader,
  Panel,
  SimulationBanner,
  Spinner,
  StatusBadge,
} from "../components/ui";
import { ChartFrame, RangeChart, ScatterChart } from "../components/Charts";
import type { PageProps } from "./types";

function evaluationTone(evaluation: ContextEvaluation): "ok" | "warn" | "danger" | "simulated" {
  if (evaluation.simulated) return "simulated";
  if (evaluation.qualified) return "ok";
  if (evaluation.status === "ineligible") return "danger";
  return "warn";
}

function confidenceText(evaluation: ContextEvaluation): string {
  if (!evaluation.interval) return "no interval";
  return `${evaluation.interval.lower.toFixed(3)} – ${evaluation.interval.upper.toFixed(3)}`;
}

function classificationCopy(response: ExperimentResultsResponse): { title: string; tone: "ok" | "warn" | "danger" | "simulated" } {
  const classification = response.finalization.classification;
  if (classification === "SIMULATED") {
    return { title: "SIMULATED — never a deployable winner", tone: "simulated" };
  }
  if (classification === "VALIDATED_WINNER") {
    return { title: "Validated winner", tone: "ok" };
  }
  return { title: "No validated winner", tone: "warn" };
}

function Comparison({ api, experimentId, navigate }: { api: PageProps["api"]; experimentId: string; navigate: PageProps["navigate"] }) {
  const results = usePolling(() => api.results(experimentId), 15_000);
  const [recipeError, setRecipeError] = useState<unknown>(null);
  const [exportError, setExportError] = useState<unknown>(null);
  const [creatingRecipe, setCreatingRecipe] = useState(false);
  const [exporting, setExporting] = useState(false);

  if (results.error) return <ErrorNotice error={results.error} onRetry={results.refresh} />;
  if (!results.data) return <Spinner label="Loading paired evidence" />;

  const response = results.data;
  const finalization = response.finalization;
  const candidates = response.candidates ?? [];
  const candidateById = new Map(candidates.map((candidate) => [candidate.candidate_id, candidate]));
  const label = (candidateId: string | null | undefined): string => {
    if (!candidateId) return "none";
    const candidate = candidateById.get(candidateId);
    if (!candidate) return shortId(candidateId, 16);
    return `#${candidate.trial_number} ${candidate.role === "baseline" ? "baseline" : CONTEXT_LABELS[candidate.context]}`;
  };

  const rangePoints = (finalization.per_context ?? []).flatMap((ranking) =>
    (ranking.evaluations ?? [])
      .filter((evaluation) => evaluation.score !== null && evaluation.score !== undefined)
      .map((evaluation) => ({
        label: `${CONTEXT_LABELS[ranking.context]} ${label(evaluation.candidate_id)}`,
        value: evaluation.score ?? 1,
        lower: evaluation.interval?.lower ?? null,
        upper: evaluation.interval?.upper ?? null,
        qualified: evaluation.qualified,
      })),
  );

  const scatterPoints = (response.observations ?? [])
    .filter((observation) => observation.metrics?.prefill_tokens_per_sec && observation.metrics?.decode_tokens_per_sec)
    .map((observation) => ({
      label: `#${observation.trial_number}`,
      x: observation.metrics?.prefill_tokens_per_sec ?? 0,
      y: observation.metrics?.decode_tokens_per_sec ?? 0,
      detail: `${CONTEXT_LABELS[observation.context]} · ${observation.evidence_kind} · ${formatBytes(observation.metrics?.gpu_vram_peak_bytes)} VRAM`,
      simulated: observation.simulated,
    }));

  const createRecipe = async () => {
    const winner = finalization.validated_winner_candidate_id;
    if (!winner) return;
    setCreatingRecipe(true);
    setRecipeError(null);
    try {
      const recipe = await api.createRecipe(experimentId, winner);
      navigate("recipes", recipe.experiment_id);
    } catch (error) {
      setRecipeError(error);
    } finally {
      setCreatingRecipe(false);
    }
  };

  const exportResults = async () => {
    setExporting(true);
    setExportError(null);
    try {
      await api.saveReport(
        `experiment-${experimentId}-results.json`,
        JSON.stringify(response, null, 2),
      );
    } catch (error) {
      setExportError(error);
    } finally {
      setExporting(false);
    }
  };

  const copy = classificationCopy(response);

  return (
    <>
      <SimulationBanner simulated={finalization.simulated ?? response.simulated ?? false} warnings={response.warnings ?? []} />
      <div className={`classification-banner classification-${copy.tone}`}>
        <div>
          <span className="eyebrow">Finalization classification</span>
          <h2>{copy.title}</h2>
          <p>
            Gate: at least {finalization.threshold_pct ?? 5}% paired improvement with a{" "}
            {Math.round((finalization.confidence_level ?? 0.95) * 100)}% confidence interval strictly above baseline
            and no guardrail failure. Highest throughput alone is never a pass.
          </p>
        </div>
        <div className="classification-actions">
          <Badge tone={copy.tone}>{finalization.classification}</Badge>
          <button className="button button-secondary" onClick={exportResults} disabled={exporting}>
            {exporting ? "Exporting…" : "Export results"}
          </button>
          {finalization.validated_winner_candidate_id ? (
            <button className="button button-primary" onClick={createRecipe} disabled={creatingRecipe}>
              {creatingRecipe ? "Creating recipe…" : "Create recipe"}
            </button>
          ) : null}
        </div>
      </div>
      {recipeError ? <ErrorNotice error={recipeError} onRetry={createRecipe} /> : null}
      {exportError ? <ErrorNotice error={exportError} onRetry={exportResults} /> : null}

      <div className="grid-2">
        <Panel title="Paired objective ratio" subtitle="Points above 1.0 beat their same-context baseline. Bars are confidence intervals.">
          <ChartFrame title="Ratio by evaluation">
            <RangeChart points={rangePoints} />
          </ChartFrame>
        </Panel>
        <Panel title="Prefill / decode frontier" subtitle="Simulated observations are marked separately; a Pareto point is not a qualification.">
          <ChartFrame title="Throughput observations">
            <ScatterChart points={scatterPoints} xLabel="Prefill tokens / second" yLabel="Decode tokens / second" />
          </ChartFrame>
          <div className="legend">
            <span><i className="legend-dot real" /> real observation</span>
            <span><i className="legend-dot simulated" /> simulated observation</span>
          </div>
        </Panel>
      </div>

      {(finalization.per_context ?? []).map((ranking) => (
        <Panel
          key={ranking.context}
          title={`${CONTEXT_LABELS[ranking.context]} context`}
          subtitle={`Baseline ${label(ranking.baseline_candidate_id)} · winner ${label(ranking.winner_candidate_id)}`}
          actions={<Badge tone={ranking.winner_candidate_id ? "ok" : "warn"}>{ranking.winner_candidate_id ? "qualified winner" : "no qualified winner"}</Badge>}
        >
          {(ranking.evaluations ?? []).length === 0 ? (
            <EmptyState title="No paired evaluations" detail="This context was selected but has no eligible paired baseline/candidate samples." />
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Candidate</th>
                    <th>Score</th>
                    <th>Improvement</th>
                    <th>Paired interval</th>
                    <th>Status</th>
                    <th>Samples (base / cand)</th>
                    <th>Reasons</th>
                  </tr>
                </thead>
                <tbody>
                  {(ranking.evaluations ?? []).map((evaluation) => (
                    <tr key={`${ranking.context}-${evaluation.candidate_id}`} className={evaluation.qualified ? "row-ok" : ""}>
                      <td><strong>{label(evaluation.candidate_id)}</strong><small>{shortId(evaluation.candidate_id, 20)}</small></td>
                      <td>{evaluation.score === null || evaluation.score === undefined ? "—" : evaluation.score.toFixed(4)}</td>
                      <td>{formatDelta(evaluation.improvement_pct)}</td>
                      <td className="mono">{confidenceText(evaluation)}</td>
                      <td><Badge tone={evaluationTone(evaluation)}>{evaluation.status ?? "unknown"}</Badge></td>
                      <td>{evaluation.baseline_samples ?? 0} / {evaluation.candidate_samples ?? 0}</td>
                      <td>
                        {evaluation.reasons?.length ? (
                          <div className="reason-list">
                            {evaluation.reasons.map((reason) => <span key={reason} className="reason-chip">{reason}</span>)}
                          </div>
                        ) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      ))}

      <Panel
        title="Cross-context ranking"
        subtitle="Aggregation requires exactly the selected, complete context set. Missing contexts make a candidate ineligible."
      >
        {!finalization.cross_context?.length ? (
          <EmptyState title="No cross-context ranking" detail="Per-context mode does not claim a global winner." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Candidate</th><th>Coverage</th><th>Aggregate score</th><th>Per-context scores</th><th>Qualified</th><th>Reasons</th></tr></thead>
              <tbody>
                {finalization.cross_context.map((ranking) => (
                  <tr key={ranking.candidate_id}>
                    <td><strong>{label(ranking.candidate_id)}</strong></td>
                    <td>{ranking.complete_coverage ? "complete" : "incomplete"} ({(ranking.contexts ?? []).map((context) => CONTEXT_LABELS[context]).join(", ") || "none"})</td>
                    <td>{ranking.score.toFixed(4)}</td>
                    <td className="mono">{(ranking.per_context_scores ?? []).map((score) => score.toFixed(3)).join(" · ") || "—"}</td>
                    <td><Badge tone={ranking.qualified ? "ok" : "warn"}>{ranking.qualified ? "qualified" : "ineligible"}</Badge></td>
                    <td>{(ranking.reasons ?? []).length ? (ranking.reasons ?? []).join(", ") : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Resource and latency facts" subtitle="TTFT and peak VRAM are reported from retained observations; they are not used to silently replace failed metrics.">
        {(response.observations ?? []).length === 0 ? (
          <EmptyState title="No observations" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Trial</th><th>Context</th><th>Prefill</th><th>Decode</th><th>TTFT</th><th>Peak VRAM</th><th>Samples</th><th>Measurement</th></tr></thead>
              <tbody>
                {(response.observations ?? []).map((observation: BenchmarkObservation) => (
                  <tr key={observation.observation_id}>
                    <td>{observation.trial_number}</td>
                    <td>{CONTEXT_LABELS[observation.context]}</td>
                    <td>{metric(observation.metrics?.prefill_tokens_per_sec, " tok/s")}</td>
                    <td>{metric(observation.metrics?.decode_tokens_per_sec, " tok/s")}</td>
                    <td>{metric(observation.metrics?.time_to_first_token_ms, " ms")}</td>
                    <td>{formatBytes(observation.metrics?.gpu_vram_peak_bytes)}</td>
                    <td>{observation.samples?.length ?? 0}</td>
                    <td>
                      <Badge tone={observation.simulated ? "simulated" : "info"}>{observation.measurement_status}</Badge>
                      <small>{observation.evidence_kind}</small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Candidate provenance">
        {candidates.length === 0 ? <EmptyState title="No candidates" /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Trial</th><th>Role</th><th>Context</th><th>State</th><th>Parameters</th><th>Candidate ID</th></tr></thead>
              <tbody>
                {candidates.map((candidate: CandidateSpec) => (
                  <tr key={candidate.candidate_id}>
                    <td>{candidate.trial_number}</td>
                    <td><Badge tone={candidate.role === "baseline" ? "info" : "neutral"}>{candidate.role ?? "candidate"}</Badge></td>
                    <td>{CONTEXT_LABELS[candidate.context]}</td>
                    <td><StatusBadge value={candidate.state} /></td>
                    <td className="mono wrap small">{JSON.stringify(candidate.parameters)}</td>
                    <td className="mono small">{shortId(candidate.candidate_id, 24)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}

export function ComparePage({
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
  const terminal = useMemo(
    () => list.filter((job) => ["completed", "failed", "cancelled", "blocked"].includes(job.state)),
    [list],
  );
  const choosable = terminal.length > 0 ? terminal : list;

  useEffect(() => {
    if (!activeExperimentId && choosable.length > 0) setActiveExperimentId(choosable[0]!.experiment_id);
  }, [activeExperimentId, choosable, setActiveExperimentId]);

  return (
    <>
      <PageHeader
        eyebrow="Paired evidence"
        title="Compare"
        description="Statistical qualification, resource facts and the Pareto frontier. Incomplete evidence is shown as ineligible, never silently promoted."
        actions={
          <label className="field-inline">
            <span>Experiment</span>
            <select value={selected ?? ""} onChange={(event) => setActiveExperimentId(event.target.value || null)}>
              <option value="">Select</option>
              {choosable.map((job) => (
                <option key={job.experiment_id} value={job.experiment_id}>
                  {job.model_id} · {job.state} · {shortId(job.experiment_id, 12)}
                </option>
              ))}
            </select>
          </label>
        }
      />
      {experimentsError ? <ErrorNotice error={experimentsError} onRetry={refreshShell} /> : null}
      {choosable.length === 0 ? (
        <Panel><EmptyState title="No results yet" detail="Start an experiment first; finalization is only available after evidence is retained." /></Panel>
      ) : selected ? (
        <Comparison key={selected} api={api} experimentId={selected} navigate={navigate} />
      ) : (
        <Panel><EmptyState title="Select an experiment" /></Panel>
      )}
      <p className="muted">
        Selected contexts: {CONTEXTS.join(", ")} tokens are available in the planner. This page reads only persisted
        finalization and observations.
      </p>
    </>
  );
}
