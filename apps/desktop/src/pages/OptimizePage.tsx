import { useLocalRuntime } from "../components/LocalRuntime";
import { ModelVerificationProgress } from "../components/ModelVerification";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  ContextLength,
  ExperimentPlan,
  Objective,
  PlanRequest,
  RecipeMode,
  SearchDepth,
  WorkerSnapshot,
} from "../lib/contracts";
import { CONTEXTS, CONTEXT_LABELS, OBJECTIVES, SEARCH_DEPTHS } from "../lib/contracts";
import type { PlanResponse } from "../lib/contracts";
import { formatBytes, shortId } from "../lib/format";
import { Badge, ErrorNotice, Notice, PageHeader, Panel, Spinner, WarningList } from "../components/ui";
import type { PageProps } from "./types";

const DEPTH_DEFAULTS: Record<SearchDepth, { maxCandidates: number; finalists: number; screening: number; final: number }> = {
  quick: { maxCandidates: 12, finalists: 2, screening: 2, final: 3 },
  standard: { maxCandidates: 36, finalists: 5, screening: 3, final: 5 },
  thorough: { maxCandidates: 96, finalists: 8, screening: 3, final: 7 },
};

const STEPS = [
  "Target",
  "Objective",
  "Contexts",
  "Search",
  "Preflight",
  "Submit",
];

export function OptimizePage({ api, navigate, refreshShell }: PageProps) {
  const runtime = useLocalRuntime();
  const inFlight = useRef(false);
  const [verificationPaused, setVerificationPaused] = useState(false);
  const [step, setStep] = useState(1);
  const [workers, setWorkers] = useState<Awaited<ReturnType<PageProps["api"]["workers"]>> | null>(null);
  const [workersError, setWorkersError] = useState<unknown>(null);
  const [workerId, setWorkerId] = useState<string>("");
  const [snapshot, setSnapshot] = useState<WorkerSnapshot | null>(null);
  const [snapshotError, setSnapshotError] = useState<unknown>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [gpuUuid, setGpuUuid] = useState<string>("");
  const [engineId, setEngineId] = useState<string>("");
  const [modelId, setModelId] = useState<string>("");
  const [objective, setObjective] = useState<Objective>("balanced");
  const [contexts, setContexts] = useState<ContextLength[]>([4096]);
  const [depth, setDepth] = useState<SearchDepth>("quick");
  const [recipeMode, setRecipeMode] = useState<RecipeMode>("per_context");
  const [maxCandidates, setMaxCandidates] = useState(DEPTH_DEFAULTS.quick.maxCandidates);
  const [finalists, setFinalists] = useState(DEPTH_DEFAULTS.quick.finalists);
  const [screening, setScreening] = useState(DEPTH_DEFAULTS.quick.screening);
  const [finalReplications, setFinalReplications] = useState(DEPTH_DEFAULTS.quick.final);
  const [threshold, setThreshold] = useState(5);
  const [confidence, setConfidence] = useState(0.95);
  const [requireFullContext, setRequireFullContext] = useState(true);
  const [quietGpu, setQuietGpu] = useState(true);
  const [planResponse, setPlanResponse] = useState<PlanResponse | null>(null);
  const [planError, setPlanError] = useState<unknown>(null);
  const [planning, setPlanning] = useState(false);
  const [createError, setCreateError] = useState<unknown>(null);
  const [creating, setCreating] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [preflightReason, setPreflightReason] = useState<string | null>(null);

  useEffect(() => {
    let stopped = false;
    setWorkersError(null);
    void api
      .workers()
      .then((data) => {
        if (stopped) return;
        setWorkers(data);
        setWorkerId((current) => current || data.workers[0]?.worker_id || "");
      })
      .catch((error: unknown) => {
        if (!stopped) setWorkersError(error);
      });
    return () => {
      stopped = true;
    };
  }, [api]);

  useEffect(() => {
    if (!workerId) return;
    let stopped = false;
    setSnapshot(null);
    setSnapshotError(null);
    setSnapshotLoading(true);
    setEngineId("");
    setModelId("");
    setGpuUuid("");
    setPlanResponse(null);
    void api
      .workerSnapshot(workerId)
      .then((data) => {
        if (stopped) return;
        setSnapshot(data);
        setGpuUuid(data.hardware.gpus?.[0]?.uuid ?? "");
        const firstEngine = data.engines?.[0]?.engine.engine_id ?? "";
        setEngineId(firstEngine);
        const compatible = [...(data.models ?? [])].filter(model =>
          (model.compatible_engines ?? []).includes(firstEngine as never)
        ).sort((a, b) => (a.size_bytes ?? Infinity) - (b.size_bytes ?? Infinity))[0];
        setModelId(compatible?.model_id ?? data.models?.[0]?.model_id ?? "");
      })
      .catch((error: unknown) => {
        if (!stopped) setSnapshotError(error);
      })
      .finally(() => {
        if (!stopped) setSnapshotLoading(false);
      });
    return () => {
      stopped = true;
    };
  }, [api, workerId]);

  const engines = snapshot?.engines ?? [];
  const models = snapshot?.models ?? [];
  const compatibleModels = models.filter((model) =>
    (model.compatible_engines ?? []).includes(engineId as never),
  );
  const selectedModel = models.find((model) => model.model_id === modelId);
  const selectedEngine = engines.find((engine) => engine.engine.engine_id === engineId);

  const resetPlan = () => {
    setPlanResponse(null);
    setVerificationPaused(false);
    setPreflightReason(null);
    setConfirmed(false);
    setCreateError(null);
  };

  const changeDepth = (next: SearchDepth) => {
    setDepth(next);
    const defaults = DEPTH_DEFAULTS[next];
    setMaxCandidates(defaults.maxCandidates);
    setFinalists(defaults.finalists);
    setScreening(defaults.screening);
    setFinalReplications(defaults.final);
    resetPlan();
  };

  const toggleContext = (context: ContextLength) => {
    setContexts((current) => {
      const next = current.includes(context)
        ? current.filter((item) => item !== context)
        : [...current, context].sort((a, b) => a - b);
      setRecipeMode(next.length > 1 ? "cross_context" : "per_context");
      return next;
    });
    resetPlan();
  };

  const request: PlanRequest = useMemo(
    () => ({
      worker_id: workerId,
      engine_id: engineId as PlanRequest["engine_id"],
      model_id: modelId,
      objective,
      contexts,
      search_depth: depth,
      search_policy: {
        depth,
        max_candidates: maxCandidates,
        finalist_count: finalists,
        screening_replications: screening,
        final_replications: finalReplications,
        min_improvement_pct: threshold,
        confidence_level: confidence,
        seed: 7,
      },
      constraints: {
        require_full_context_proof: requireFullContext,
        quiet_gpu_required: quietGpu,
      },
      recipe_mode: recipeMode,
      gpu_uuids: gpuUuid ? [gpuUuid] : [],
    }),
    [
      confidence,
      contexts,
      depth,
      engineId,
      finalReplications,
      finalists,
      gpuUuid,
      maxCandidates,
      modelId,
      objective,
      quietGpu,
      recipeMode,
      requireFullContext,
      screening,
      threshold,
      workerId,
    ],
  );

  const canContinue = (() => {
    if (step === 1) {
      const gpuRequired = (snapshot?.hardware.gpus?.length ?? 0) > 0;
      return Boolean(workerId && engineId && modelId && selectedModel && selectedEngine && (!gpuRequired || gpuUuid));
    }
    if (step === 2) return Boolean(objective);
    if (step === 3) return contexts.length > 0;
    if (step === 4) return Number.isInteger(maxCandidates) && maxCandidates >= 1 && maxCandidates <= 500 && Number.isInteger(finalists) && finalists >= 1 && finalists <= Math.min(20, maxCandidates) && Number.isInteger(screening) && screening >= 1 && screening <= 20 && Number.isInteger(finalReplications) && finalReplications >= 2 && finalReplications <= 50 && Number.isFinite(threshold) && threshold >= 0 && threshold <= 100;
    return true;
  })();

  const runPlan = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setVerificationPaused(false);
    setPlanning(true);
    setPlanError(null);
    setCreateError(null);
    setPreflightReason(null);
    try {
      const response = await api.plan(request);
      setPlanResponse(response);
      if (response.status === "preflight_required") {
        setPreflightReason(
          response.reason ??
            `Preflight required. A SCAN command ${response.command_id ? `(${response.command_id})` : ""} was queued by the controller.`,
        );
      }
    } catch (error) {
      setPlanError(error);
    } finally {
      inFlight.current = false;
      setPlanning(false);
    }
  }, [api, request]);

  useEffect(() => {
    if (step === 5 && !planResponse && !planning && !planError) void runPlan();
  }, [step, planResponse, planning, planError, runPlan]);

  useEffect(() => {
    if (step !== 5 || planResponse?.status !== "preflight_required" || verificationPaused || planning) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const commands = await api.workerCommands(workerId);
        if (stopped) return;
        const command = commands.find(item => item.command_id === planResponse.command_id);
        if (!command) throw new Error("The verification job was not found. Refresh the worker and try again.");
        if (["failed", "rejected", "cancelled", "expired"].includes(command.status)) throw new Error(command.failure?.message ?? "Model verification stopped. Check the worker and model file permissions, then retry.");
        if (command.status === "completed") {
          const fresh = await api.workerSnapshot(workerId);
          if (stopped) return;
          setSnapshot(fresh);
          const model = fresh.models?.find(item => item.model_id === modelId);
          if (!model || !model.files?.length || (planResponse.reason?.includes("selected model files") && model.files.some(file => !file.sha256 || !file.verified))) {
            throw new Error("Some selected model files could not be verified. Check file access and model discovery warnings, then retry.");
          }
          const response = await api.plan(request);
          if (stopped) return;
          setPlanResponse(response); setPreflightReason(response.reason ?? null);
          return;
        }
        setPreflightReason(command.status === "pending" ? "Waiting for the worker to start file verification. You do not need to re-check the plan." : "Verifying model files. Large libraries can take several minutes; the plan continues automatically when ready.");
      } catch (error) { if (!stopped) { setPlanError(error); setVerificationPaused(true); } return; }
      if (!stopped) timer = setTimeout(poll, 2000);
    };
    timer = setTimeout(poll, Math.max(500, Math.min(planResponse.retry_after_ms ?? 2000, 5000)));
    return () => { stopped = true; clearTimeout(timer); };
  }, [api, workerId, modelId, request, step, planResponse, verificationPaused, planning]);

  const waitingForVerification = planResponse?.status === "preflight_required" && !verificationPaused;
  const createExperiment = async () => {
    if (planResponse?.status !== "ready" || !planResponse.plan || !confirmed || api.demo) return;
    setCreating(true);
    setCreateError(null);
    try {
      const view = await api.createExperiment(planResponse.plan);
      refreshShell();
      navigate("live", view.status.experiment_id);
    } catch (error) {
      setCreateError(error);
    } finally {
      setCreating(false);
    }
  };

  const feasibility = planResponse?.plan?.feasibility ?? [];
  const selectedFeasibility = (context: number) => feasibility.find((item) => item.context === context);
  const incompatible = models.filter((model) => !compatibleModels.includes(model));

  return (
    <>
      <PageHeader
        eyebrow="Immutable experiment wizard"
        title="Optimize"
        description="Choose a model and what to improve. We prepare the files and check readiness before you start the test."
        actions={<Badge tone="info">{api.demo ? "Demo plan only" : "Real controller"}</Badge>}
      />

      <ol className="stepper">
        {STEPS.map((label, index) => {
          const number = index + 1;
          return (
            <li key={label} className={number === step ? "active" : number < step ? "done" : ""}>
              <button aria-current={number === step ? "step" : undefined} disabled={number > step} onClick={() => number < step && setStep(number)}>
                <span>{number}</span>
                {label}
              </button>
            </li>
          );
        })}
      </ol>

      {workersError ? <ErrorNotice error={workersError} /> : null}
      {snapshotError ? <ErrorNotice error={snapshotError} /> : null}

      {step === 1 ? (
        <div className="grid-2">
          <Panel title="Target worker" subtitle="Only cached inventory from a registered worker is selectable.">
            {!workers && !workersError ? <Spinner label="Loading workers" /> : null}
            {workers?.workers.length === 0 ? (
              <Notice tone="warn" title="No workers registered">
                Start the controller and register a worker. The UI cannot start or enroll a worker itself.
              </Notice>
            ) : null}
            <div className="choice-list">
              {workers?.workers.map((worker) => (
                <label key={worker.worker_id} className={`choice-card ${workerId === worker.worker_id ? "selected" : ""}`}>
                  <input
                    type="radio"
                    name="worker"
                    checked={workerId === worker.worker_id}
                    onChange={() => {
                      setWorkerId(worker.worker_id);
                      resetPlan();
                    }}
                  />
                  <span>
                    <strong>{worker.name}</strong>
                    <small>{worker.worker_id}</small>
                  </span>
                  <Badge tone={worker.status === "online" ? "ok" : "warn"}>{worker.status}</Badge>
                </label>
              ))}
            </div>
            {snapshot && (snapshot.hardware.gpus?.length ?? 0) > 0 ? (
              <label className="field">
                <span>Target GPU</span>
                <select
                  value={gpuUuid}
                  onChange={(event) => {
                    setGpuUuid(event.target.value);
                    resetPlan();
                  }}
                >
                  {snapshot.hardware.gpus?.map((gpu) => (
                    <option key={gpu.uuid} value={gpu.uuid}>
                      {gpu.name} · {formatBytes(gpu.vram_total_bytes)} · {gpu.uuid}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {workers?.workers.length ? (
              <p className="muted">GPU: {snapshot?.hardware.gpus?.map((gpu) => gpu.name).join(", ") || "loading inventory…"}</p>
            ) : null}
          </Panel>

          <Panel title="Engine and model" subtitle="Compatibility comes from the observed snapshot, not a curated guess.">
            {snapshotLoading ? <Spinner label="Loading cached inventory" /> : null}
            {!snapshotLoading && !snapshot ? <p className="muted">Select a worker with a cached snapshot.</p> : null}
            {snapshot ? (
              <>
                <label className="field">
                  <span>Installed engine</span>
                  <select
                    value={engineId}
                    onChange={(event) => {
                      setEngineId(event.target.value);
                      const first = models.filter((model) =>
                        (model.compatible_engines ?? []).includes(event.target.value as never),
                      ).sort((a, b) => (a.size_bytes ?? Infinity) - (b.size_bytes ?? Infinity))[0];
                      setModelId(first?.model_id ?? "");
                      resetPlan();
                    }}
                  >
                    {engines.map((engine) => (
                      <option key={engine.engine.engine_id} value={engine.engine.engine_id}>
                        {engine.engine.engine_id} · {engine.engine.version} · build {engine.engine.build}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Compatible installed model</span>
                  <select value={modelId} onChange={(event) => { setModelId(event.target.value); resetPlan(); }}>
                    {compatibleModels.map((model) => (
                      <option key={model.model_id} value={model.model_id}>
                        {model.display_name} · {model.quantization ?? "unknown"}
                      </option>
                    ))}
                  </select>
                </label>
                {compatibleModels.length === 0 ? (
                  <Notice tone="warn" title="No compatible model">
                    The selected engine has no compatible model in the cached snapshot.
                  </Notice>
                ) : null}
                {incompatible.length > 0 ? (
                  <p className="muted">
                    Hidden or disabled because compatibility is not proven: {incompatible.map((model) => model.display_name).join(", ")}.
                  </p>
                ) : null}
                {selectedModel ? (
                  <div className="target-summary">
                    <strong>{selectedModel.display_name}</strong>
                    <span>{formatBytes(selectedModel.size_bytes)} · {selectedModel.quantization ?? "unknown"}</span>
                    <span className="mono">{shortId(selectedModel.model_id, 26)}</span>
                  </div>
                ) : null}
              </>
            ) : null}
          </Panel>
        </div>
      ) : null}

      {step === 2 ? (
        <Panel title="Objective" subtitle="Scores use paired baseline ratios. No hidden weights.">
          <div className="choice-list">
            {OBJECTIVES.map((option) => (
              <label key={option.value} className={`choice-card tall ${objective === option.value ? "selected" : ""}`}>
                <input
                  type="radio"
                  name="objective"
                  checked={objective === option.value}
                  onChange={() => { setObjective(option.value); resetPlan(); }}
                />
                <span>
                  <strong>{option.label}</strong>
                  <small>{option.description}</small>
                </span>
              </label>
            ))}
          </div>
        </Panel>
      ) : null}

      {step === 3 ? (
        <Panel
          title="Contexts"
          subtitle="Choose the conversation lengths to test. Memory fit is checked automatically when the test starts; start with 4K for a shorter first run."
        >
          <div className="context-grid">
            {CONTEXTS.map((context) => {
              const result = selectedFeasibility(context);
              const selected = contexts.includes(context);
              return (
                <button
                  type="button"
                  key={context}
                  aria-pressed={selected}
                  className={`context-card ${selected ? "selected" : ""}`}
                  onClick={() => toggleContext(context)}
                >
                  <div>
                    <strong>{CONTEXT_LABELS[context]}</strong>
                    <small>{context.toLocaleString()} tokens</small>
                  </div>
                  <span className="checkbox-mark">{selected ? "✓" : ""}</span>
                  {result ? (
                    <Badge tone={result.status === "feasible" ? "ok" : result.status === "unknown" || result.status === "inconclusive" ? "warn" : "danger"}>
                      {result.status?.replaceAll("_", " ") ?? "unknown"}
                    </Badge>
                  ) : (
                    <Badge tone="neutral">Checked when test starts</Badge>
                  )}
                </button>
              );
            })}
          </div>
          <label className="field">
            <span>Recipe mode</span>
            <select value={recipeMode} onChange={(event) => { setRecipeMode(event.target.value as RecipeMode); resetPlan(); }}>
              <option value="cross_context">Cross-context — one full-coverage recipe</option>
              <option value="per_context">Per-context — one winner per context</option>
            </select>
          </label>
          {contexts.length > 1 && recipeMode === "cross_context" ? (
            <Notice tone="info" title="Complete coverage required">
              A cross-context winner requires every selected context to have a qualified paired baseline and candidate.
              Missing contexts remain visible but cannot produce a global winner.
            </Notice>
          ) : null}
        </Panel>
      ) : null}

      {step === 4 ? (
        <div className="grid-2">
          <Panel title="Search depth" subtitle="Budget caps are explicit. The controller enforces them.">
            <Notice title="Comparing with your manual tests"><p>A finite search finds the best settings it tested. It can miss your hand-tuned configuration. For a fair comparison, match the model and engine build, context, prompt and generated token counts, cache state, GPU load and reasoning mode. Generation max targets output speed; Balanced also scores prompt processing. More candidates explore more settings, without guaranteeing a faster result.</p></Notice>
            {engineId === "strata" ? <Notice tone="warn" title="Strata search coverage"><p>This search keeps experts file-backed and does not explore resident-expert or asynchronous adaptation profiles. A manually tuned profile using those settings may be faster. Compare matching workloads and timing methods; app rates are measured from the client, so engine-only rates are not interchangeable.</p></Notice> : null}
            <button className="button button-secondary" onClick={() => {
              setDepth("quick"); setMaxCandidates(1); setFinalists(1); setScreening(1); setFinalReplications(2);
              setContexts([4096]); setRecipeMode("per_context"); setObjective("balanced");
              setQuietGpu(true); setRequireFullContext(true); resetPlan();
            }}>Small setup test</button>
            <p className="muted">Check your setup with one 4K context, one candidate and the minimum repetitions. Duration is unknown until the engine runs. This does not guarantee a validated recipe.</p>
            <div className="choice-list">
              {SEARCH_DEPTHS.map((option) => (
                <label key={option.value} className={`choice-card tall ${depth === option.value ? "selected" : ""}`}>
                  <input type="radio" name="depth" checked={depth === option.value} onChange={() => changeDepth(option.value)} />
                  <span>
                    <strong>{option.label}</strong>
                    <small>{option.detail}</small>
                  </span>
                </label>
              ))}
            </div>
            <Notice tone="info" title="Baselines are controls">
              The controller asks one fixed-default baseline per selected context before TPE proposals. Baselines are not
              counted against the distinct-candidate search budget.
            </Notice>
          </Panel>
          <Panel title="Advanced limits" subtitle="Changes create a new plan; they never mutate an existing study.">
            <details className="advanced-limits"><summary>Adjust budgets and qualification</summary>
            <div className="form-grid">
              <label className="field">
                <span>Max distinct candidates</span>
                <input type="number" min={1} max={500} value={maxCandidates} onChange={(event) => { setMaxCandidates(Number(event.target.value)); resetPlan(); }} />
              </label>
              <label className="field">
                <span>Finalists</span>
                <input type="number" min={1} max={20} value={finalists} onChange={(event) => { setFinalists(Number(event.target.value)); resetPlan(); }} />
              </label>
              <label className="field">
                <span>Screening replications</span>
                <input type="number" min={1} max={20} value={screening} onChange={(event) => { setScreening(Number(event.target.value)); resetPlan(); }} />
              </label>
              <label className="field">
                <span>Final replications</span>
                <input type="number" min={2} max={50} value={finalReplications} onChange={(event) => { setFinalReplications(Number(event.target.value)); resetPlan(); }} />
              </label>
              <label className="field">
                <span>Minimum improvement (%)</span>
                <input type="number" min={0} max={100} step={0.5} value={threshold} onChange={(event) => { setThreshold(Number(event.target.value)); resetPlan(); }} />
              </label>
              <label className="field">
                <span>Confidence level</span>
                <select value={confidence} onChange={(event) => { setConfidence(Number(event.target.value)); resetPlan(); }}>
                  <option value={0.95}>95%</option>
                  <option value={0.99}>99%</option>
                </select>
              </label>
            </div>
            <label className="checkbox-row">
              <input type="checkbox" checked={requireFullContext} onChange={(event) => { setRequireFullContext(event.target.checked); resetPlan(); }} />
              Require full-context proof for qualification
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={quietGpu} onChange={(event) => { setQuietGpu(event.target.checked); resetPlan(); }} />
              Require a quiet GPU and reject contaminated trials
            </label>
            </details>
          </Panel>
        </div>
      ) : null}

      {step === 5 ? (
        <div className="grid-2">
          <Panel title="Check readiness" subtitle="We verify model files and prepare the test automatically. No manual terminal steps are needed.">
            <div className="review-list">
              <ReviewRow label="Worker" value={workerId || "not selected"} />
              <ReviewRow label="GPU" value={gpuUuid || "no GPU selected"} />
              <ReviewRow label="Engine" value={engineId ? `${engineId} · ${selectedEngine?.engine.version ?? "unknown"}` : "not selected"} />
              <ReviewRow label="Model" value={selectedModel?.display_name ?? "not selected"} />
              <ReviewRow label="Objective" value={objective} />
              <ReviewRow label="Contexts" value={contexts.map((context) => CONTEXT_LABELS[context]).join(", ") || "none"} />
              <ReviewRow label="Search" value={`${depth} · ${maxCandidates} candidates · ${finalists} finalists`} />
              <ReviewRow label="Gate" value={`≥${threshold}% improvement · ${Math.round(confidence * 100)}% paired interval`} />
            </div>
            <button className="button button-primary" onClick={runPlan} disabled={planning || waitingForVerification || !canContinue}>
              {waitingForVerification ? "Verification in progress…" : planning ? "Checking…" : "Retry readiness check"}
            </button>
            {planError ? <ErrorNotice error={planError} onRetry={runPlan} /> : null}
            {preflightReason ? <Notice tone={verificationPaused ? "warn" : "info"} title={verificationPaused ? "Needs attention" : "Preparing your test"}>{preflightReason}</Notice> : null}
            <ModelVerificationProgress value={api.demo ? undefined : runtime.data?.inventory?.verification} />
          </Panel>
          <Panel title="Plan result">
            {!planResponse ? (
              <p className="muted">Run a plan check to see snapshot feasibility and the immutable review.</p>
            ) : (
              <>
                <div className="plan-status">
                  <Badge tone={planResponse.status === "ready" ? "info" : "warn"}>{planResponse.status === "preflight_required" ? verificationPaused ? "Needs attention" : "Checking model files" : "Plan ready to submit"}</Badge>
                  {planResponse.plan ? <span className="mono">{shortId(planResponse.plan.plan_id, 24)}</span> : null}
                </div>
                {planResponse.status === "preflight_required" ? <Notice tone="warn" title="Preflight required — submission blocked">
                  <p>{planResponse.reason}</p><p>Queued command: <code>{planResponse.command_id}</code></p>
                  <p>The controller must return a fresh ready plan before review and submission.</p>
                </Notice> : null}
                {planResponse.plan ? (
                  <>
                    <p className="muted">
                      Inventory snapshot revision {planResponse.plan.worker_snapshot_revision ?? "unknown"} · digest{" "}
                      <span className="mono">{shortId(planResponse.plan.inventory_snapshot_digest, 20)}</span>
                    </p>
                    <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable data table">
                      <table>
                        <thead><tr><th scope="col">Context</th><th scope="col">Feasibility</th><th scope="col">Required proof</th><th scope="col">Evidence</th></tr></thead>
                        <tbody>
                          {(planResponse.plan.feasibility ?? []).map((item) => (
                            <tr key={item.context}>
                              <td>{CONTEXT_LABELS[item.context]}</td>
                              <td><Badge tone={item.status === "feasible" ? "ok" : item.status === "unknown" ? "neutral" : "warn"}>{item.status === "unknown" ? "Checked during test" : item.status ?? "Checked during test"}</Badge></td>
                              <td>{item.requires_full_context_proof ? "yes" : "no"}</td>
                              <td>{item.reason ?? item.evidence?.[0] ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {(planResponse.plan.warnings?.length ?? 0) > 0 ? (
                      <WarningList warnings={planResponse.plan.warnings ?? []} />
                    ) : null}
                    <p className="muted">The worker still needs to check context fit and safe execution before measurements begin.</p>
                  </>
                ) : null}
              </>
            )}
          </Panel>
        </div>
      ) : null}

      {step === 6 && planResponse?.plan ? (
        <div className="grid-2">
          <Panel title="Immutable experiment review" subtitle="Submission returns a durable job ID only after commit.">
            <PlanSummary plan={planResponse.plan} />
            <label className="checkbox-row confirmation">
              <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
              I understand this creates one immutable study. Minimizing keeps local services running. Quit may stop desktop-managed local work; independent services continue.
            </label>
            {createError ? <ErrorNotice error={createError} onRetry={createExperiment} /> : null}
            {api.demo ? <Notice tone="info" title="Demo plan only">Submission is unavailable in offline demo mode. No job will be created.</Notice> : null}
            <button className="button button-primary" onClick={createExperiment} disabled={api.demo || !confirmed || creating || planResponse.status !== "ready"}>
              {creating ? "Creating durable job…" : "Create experiment"}
            </button>
          </Panel>
          <Panel title="What happens next" subtitle="The controller owns the job; the worker owns processes.">
            <ol className="timeline-list">
              <li><strong>Preflight</strong><span>Cached inventory is checked; a SCAN/PREFLIGHT command may be queued.</span></li>
              <li><strong>Paired baseline</strong><span>One fixed-default baseline runs per selected context.</span></li>
              <li><strong>Screening</strong><span>TPE proposes candidate configurations within the declared budget.</span></li>
              <li><strong>Finalization</strong><span>Retained primary samples are compared with the same-context baseline.</span></li>
              <li><strong>Recipe</strong><span>Only a measured, qualified candidate can become a validated recipe.</span></li>
            </ol>
            <Notice tone="warn" title="Simulation boundary">
              If the controller uses the simulation lane, the result will be labelled SIMULATED and can never produce a
              deployable recipe.
            </Notice>
          </Panel>
        </div>
      ) : null}

      {!canContinue ? <Notice tone="warn" title="Selection needs attention">{step === 1 ? "Select a compatible worker, engine, model and GPU from cached inventory." : step === 3 ? "Choose at least one context." : "Use whole-number budgets within the shown limits. Finalists cannot exceed the candidate budget; final repetitions must be at least two."}</Notice> : null}
      <div className="wizard-nav">
        <button className="button button-secondary" onClick={() => setStep((value) => Math.max(1, value - 1))} disabled={step === 1}>
          Back
        </button>
        <div className="wizard-progress" role="status">Step {step} of {STEPS.length}</div>
        {step < 5 ? (
          <button className="button button-primary" onClick={() => setStep((value) => Math.min(6, value + 1))} disabled={!canContinue}>
            Continue
          </button>
        ) : step === 5 ? (
          <button className="button button-primary" onClick={planResponse?.status === "ready" ? () => setStep(6) : runPlan} disabled={planning || waitingForVerification || !canContinue}>
            {planResponse?.status === "ready" ? "Review and start test" : waitingForVerification ? "Verification in progress…" : planning ? "Checking…" : "Retry readiness check"}
          </button>
        ) : (
          <button className="button button-secondary" onClick={() => setStep(5)}>Review plan</button>
        )}
      </div>
    </>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="review-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PlanSummary({ plan }: { plan: ExperimentPlan }) {
  return (
    <>
      <div className="review-list">
        <ReviewRow label="Plan ID" value={plan.plan_id} />
        <ReviewRow label="Worker" value={plan.spec.worker_id} />
        <ReviewRow label="Engine" value={`${plan.spec.engine.engine_id} · ${plan.spec.engine.version} · build ${plan.spec.engine.build}`} />
        <ReviewRow label="Model" value={plan.spec.model.display_name} />
        <ReviewRow label="Objective" value={plan.spec.objective} />
        <ReviewRow label="Contexts" value={plan.spec.contexts.map((context) => CONTEXT_LABELS[context]).join(", ")} />
        <ReviewRow label="Recipe mode" value={plan.spec.recipe_mode ?? "per_context"} />
        <ReviewRow label="Search depth" value={plan.spec.search_depth} />
        <ReviewRow label="Max candidates" value={String(plan.spec.search_policy.max_candidates ?? "default")} />
        <ReviewRow label="Gate" value={`≥${plan.spec.search_policy.min_improvement_pct ?? 5}% · ${Math.round((plan.spec.search_policy.confidence_level ?? 0.95) * 100)}%`} />
        <ReviewRow label="Inventory digest" value={shortId(plan.inventory_snapshot_digest, 30)} />
      </div>
      {(plan.warnings?.length ?? 0) > 0 ? (
        <WarningList warnings={plan.warnings ?? []} />
      ) : null}
    </>
  );
}
