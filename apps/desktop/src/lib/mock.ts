import type {
  BenchmarkObservation,
  CandidateSpec,
  ComparisonCreateRequest,
  ComparisonEvidenceRequest,
  ComparisonListResponse,
  ComparisonPlan,
  ComparisonResult,
  ContextEvaluation,
  EngineIdentity,
  ExperimentPlan,
  ExperimentResultsResponse,
  ExperimentStatusView,
  ExperimentView,
  FinalizationResult,
  GPUDevice,
  ImpactAssessment,
  ModelArtifact,
  PlanRequest,
  PlanResponse,
  RecipeView,
  ReleaseCheckRequest,
  ReleaseCheckResponse,
  ReleaseDetailResponse,
  ReleaseListResponse,
  ReleaseMetadata,
  ReleaseNoticeView,
  SearchPolicy,
  SystemStatusResponse,
  WorkerListResponse,
  WorkerSnapshot,
} from "./contracts";

const NOW = "2026-10-21T00:00:00Z";
const SHA = "a".repeat(64);

const GPU: GPUDevice = {
  index: 0,
  name: "NVIDIA GeForce RTX 3060",
  uuid: "GPU-078cc33c-e5cb-0cb2-2ac3-95f087497407",
  vram_total_bytes: 12_884_901_888,
  driver_version: "580.95.05",
  compute_capability: "8.6",
  owned_by_lab: true,
};

const MODEL: ModelArtifact = {
  model_id: "qwen2.5-7b-instruct-q4_k_m",
  display_name: "Qwen2.5 7B Instruct Q4_K_M",
  architecture: "qwen2",
  quantization: "Q4_K_M",
  size_bytes: 4_683_000_000,
  model_family: "qwen2",
  tokenizer_id: "qwen2",
  verified: true,
  compatible_engines: ["llamacpp", "strata"],
  files: [
    {
      path: "qwen2.5-7b-instruct-q4_k_m.gguf",
      size_bytes: 4_683_000_000,
      sha256: SHA,
      verified: true,
    },
  ],
};

export const DEMO_SNAPSHOT: WorkerSnapshot = {
  snapshot_id: "snap-demo-1",
  worker_id: "lab-worker-1",
  revision: 4,
  created_at: NOW,
  discovery_digest: SHA,
  hardware: {
    hostname: "lab-rtx3060",
    os: "Ubuntu 24.04",
    kernel: "6.8.0-45-generic",
    cpu_model: "AMD Ryzen 7 5800X",
    cpu_threads: 16,
    ram_total_bytes: 34_359_738_368,
    ram_available_bytes: 21_474_836_480,
    cuda_driver_version: "580.95.05",
    cuda_runtime_version: "12.9",
    gpus: [GPU],
    contamination_warnings: [],
    collected_at: NOW,
  },
  engines: [
    {
      probed_at: NOW,
      backend: "cuda",
      engine: {
        engine_id: "llamacpp",
        version: "0.7.0-dev",
        build: "701",
        backend: "cuda",
        executable_id: "llama-server",
        executable_path: "/home/pouya/ai-lab/Inference/llama.cpp/build/bin/llama-server",
        executable_sha256: SHA,
        source_commit: "dd002b91f",
        adapter_schema: "1.0.0",
      },
      descriptors: [
        {
          key: "gpu_layers",
          kind: "int",
          support: "supported",
          minimum: -1,
          maximum: 100,
          step: 1,
          default: -1,
          impact_class: "P0",
          provenance: "observed_cli",
        },
        {
          key: "flash_attn",
          kind: "enum",
          support: "supported",
          legal_values: ["on", "off", "auto"],
          default: "auto",
          impact_class: "P0",
          provenance: "observed_cli",
        },
      ],
      notes: ["Capabilities parsed from installed --help output."],
    },
    {
      probed_at: NOW,
      backend: "cuda",
      engine: {
        engine_id: "strata",
        version: "0.1.44.1",
        build: "0.1.44.1",
        backend: "cuda",
        executable_id: "strata",
        executable_path: "/home/pouya/ai-lab/Inference/strata/bin/strata",
        executable_sha256: SHA,
        adapter_schema: "1.0.0",
      },
      descriptors: [
        {
          key: "context",
          kind: "int",
          support: "supported",
          minimum: 512,
          maximum: 131072,
          default: 4096,
          impact_class: "P0",
          provenance: "observed_cli",
        },
      ],
      notes: ["Calibration commands are not exposed by this build."],
    },
  ],
  models: [
    MODEL,
    {
      model_id: "llama-3.1-8b-instruct-q5_k_m",
      display_name: "Llama 3.1 8B Instruct Q5_K_M",
      architecture: "llama",
      quantization: "Q5_K_M",
      size_bytes: 5_740_000_000,
      model_family: "llama",
      verified: false,
      compatible_engines: ["llamacpp"],
      files: [
        {
          path: "llama-3.1-8b-instruct-q5_k_m.gguf",
          size_bytes: 5_740_000_000,
          sha256: null,
          verified: false,
        },
      ],
    },
  ],
  health: {
    status: "online",
    last_heartbeat_at: NOW,
    active_leases: [],
    owned_pids: [],
    warnings: [],
    isolated: false,
  },
  notes: ["Offline demonstration inventory. No worker or engine was contacted."],
};

export const DEMO_WORKERS: WorkerListResponse = {
  total: 1,
  workers: [
    {
      worker_id: "lab-worker-1",
      name: "RTX 3060 lab worker",
      status: "online",
      protocol_version: "1.0",
      last_heartbeat_at: NOW,
      snapshot_revision: 4,
      snapshot_created_at: NOW,
      gpus: [GPU],
      warnings: [],
    },
  ],
};

const MODEL_DIGEST = "c".repeat(64);
const CANDIDATE_SHA = "b".repeat(64);
const BASELINE_ENGINE: EngineIdentity = DEMO_SNAPSHOT.engines![0]!.engine;
const CANDIDATE_ENGINE: EngineIdentity = {
  ...BASELINE_ENGINE,
  version: "0.7.1-demo",
  build: "702-demo",
  executable_sha256: CANDIDATE_SHA,
  source_commit: "candidate-demo",
  source_digest: CANDIDATE_SHA,
};

export const DEMO_RELEASE: ReleaseMetadata = {
  engine_id: "llamacpp",
  version: "0.7.1-demo",
  build: "702-demo",
  backend: "cuda",
  executable_id: "llama-server",
  source_commit: "candidate-demo",
  artifact_sha256: CANDIDATE_SHA,
  released_at: NOW,
  source: "offline_import",
  changelog: "DEMO_DATA: imported release metadata. No artifact was downloaded or installed.",
  changed_paths: ["ggml/src/ggml-cuda/mmq.cu", "src/llama-kv-cache.cpp"],
  notes: ["Offline fixture only."],
};

const DOCS_RELEASE: ReleaseMetadata = {
  ...DEMO_RELEASE,
  version: "0.7.2-demo",
  build: "703-demo",
  artifact_sha256: null,
  source_commit: "docs-demo",
  changed_paths: ["docs/release-notes.md"],
  changelog: "DEMO_DATA: documentation-only release metadata.",
};

export const DEMO_RELEASE_NOTICE: ReleaseNoticeView = {
  notice_id: "rel-demo-cuda",
  release: DEMO_RELEASE,
  metadata_digest: "1".repeat(64),
  imported_at: NOW,
  decision: "comparison_requested",
  decision_note: "A/B proposal is retained; the current build remains installed.",
  decision_at: NOW,
};

const DOCS_RELEASE_NOTICE: ReleaseNoticeView = {
  notice_id: "rel-demo-docs",
  release: DOCS_RELEASE,
  metadata_digest: "2".repeat(64),
  imported_at: NOW,
  decision: "deferred",
  decision_note: "Documentation-only metadata does not justify a rerun.",
  decision_at: NOW,
};

const DEMO_IMPACT: ImpactAssessment = {
  assessment_id: "impact-demo-cuda",
  notice_id: DEMO_RELEASE_NOTICE.notice_id,
  worker_id: "lab-worker-1",
  model_id: MODEL.model_id,
  model_digest: MODEL_DIGEST,
  model_identity_complete: true,
  engine_id: "llamacpp",
  current_engine: BASELINE_ENGINE,
  candidate_engine_sha256: CANDIDATE_SHA,
  inventory_digest: SHA,
  inventory_snapshot_revision: 4,
  inventory_fresh: true,
  gpu_uuids: [GPU.uuid],
  impact: "P0",
  applicable: true,
  requires_smoke: true,
  requires_ab: true,
  recommended_action: "targeted_rerun",
  reasons: ["P0_RELEASE_AREA", "CAPABILITY_SCHEMA_CHANGED"],
  changed_areas: ["cuda_kernel", "kv_cache"],
  capability_diff: { added: [], removed: [], changed: ["flash_attn"], impact_class: "P0" },
};

const DOCS_IMPACT: ImpactAssessment = {
  ...DEMO_IMPACT,
  assessment_id: "impact-demo-docs",
  notice_id: DOCS_RELEASE_NOTICE.notice_id,
  impact: "P2",
  requires_smoke: false,
  requires_ab: false,
  recommended_action: "ignore",
  reasons: ["DOCUMENTATION_ONLY"],
  changed_areas: ["documentation"],
  capability_diff: { added: [], removed: [], changed: [] },
};

const DEMO_REGRESSION: ComparisonResult = {
  comparison_id: "cmp-demo-regression",
  status: "regressed",
  objective: "balanced",
  min_improvement_pct: 5,
  confidence_level: 0.95,
  evaluated_at: NOW,
  upgrade_approved: false,
  recommendation: "keep_current",
  reasons: ["4096:SIGNIFICANT_REGRESSION"],
  contexts: [
    {
      context: 4096,
      status: "regressed",
      sample_count: 3,
      score: 0.941,
      improvement_pct: -5.9,
      interval: {
        confidence_level: 0.95,
        method: "paired_percentile_bootstrap",
        point_estimate: 0.941,
        lower: 0.928,
        upper: 0.962,
        resamples: 10_000,
        sample_count: 3,
      },
      reasons: ["SIGNIFICANT_REGRESSION"],
    },
  ],
};

export const DEMO_COMPARISON: ComparisonPlan = {
  comparison_id: DEMO_REGRESSION.comparison_id,
  notice_id: DEMO_RELEASE_NOTICE.notice_id,
  assessment_id: DEMO_IMPACT.assessment_id,
  worker_id: "lab-worker-1",
  model_id: MODEL.model_id,
  model_digest: MODEL_DIGEST,
  baseline_engine: BASELINE_ENGINE,
  candidate_engine: CANDIDATE_ENGINE,
  contexts: [4096],
  objective: "balanced",
  min_improvement_pct: 5,
  confidence_level: 0.95,
  gpu_uuids: [GPU.uuid],
  status: "regressed",
  result: DEMO_REGRESSION,
  evidence_digest: "3".repeat(64),
  created_at: NOW,
  evaluated_at: NOW,
};

export const DEMO_RELEASES: ReleaseListResponse = {
  total: 2,
  notices: [DEMO_RELEASE_NOTICE, DOCS_RELEASE_NOTICE],
};

const DEMO_ASSESSMENTS: Record<string, ImpactAssessment[]> = {
  [DEMO_RELEASE_NOTICE.notice_id]: [DEMO_IMPACT],
  [DOCS_RELEASE_NOTICE.notice_id]: [DOCS_IMPACT],
};

export const DEMO_COMPARISONS: ComparisonListResponse = {
  total: 1,
  comparisons: [DEMO_COMPARISON],
};

const SPEC = {
  worker_id: "lab-worker-1",
  engine: DEMO_SNAPSHOT.engines![0]!.engine,
  model: MODEL,
  objective: "balanced" as const,
  contexts: [4096, 8192] as [4096, 8192],
  search_depth: "quick" as const,
  search_policy: {
    depth: "quick" as const,
    max_candidates: 12,
    screening_replications: 1,
    finalist_count: 2,
    final_replications: 3,
    min_improvement_pct: 5,
    confidence_level: 0.95,
    seed: 7,
  },
  constraints: {
    require_full_context_proof: true,
    quiet_gpu_required: true,
    min_free_vram_bytes: 1_073_741_824,
  },
  recipe_mode: "per_context" as const,
  inventory_snapshot_digest: SHA,
  gpu_uuids: [GPU.uuid],
};

const PLAN: ExperimentPlan = {
  plan_id: "plan-demo-20261021",
  status: "ready",
  inventory_snapshot_digest: SHA,
  worker_snapshot_revision: 4,
  spec: SPEC,
  feasibility: [
    {
      context: 4096,
      status: "feasible",
      requires_full_context_proof: true,
      estimated_vram_bytes: 5_368_709_120,
      evidence: ["Demonstration projection only; no live preflight was run."],
    },
    {
      context: 8192,
      status: "feasible",
      requires_full_context_proof: true,
      estimated_vram_bytes: 6_442_450_944,
      evidence: ["Demonstration projection only; no live preflight was run."],
    },
  ],
  warnings: ["DEMO_DATA: offline fixtures, not measured engine evidence."],
  created_at: NOW,
  stage: "queued",
};

const STATUS_SIMULATED: ExperimentStatusView = {
  experiment_id: "exp-demo-simulated",
  worker_id: "lab-worker-1",
  engine_id: "llamacpp",
  model_id: MODEL.model_id,
  objective: "balanced",
  contexts: [4096, 8192],
  state: "completed",
  stage: "completed",
  paused: false,
  revision: 14,
  plan_digest: SHA,
  spec_digest: SHA,
  counters: {
    candidates_proposed: 3,
    candidates_completed: 3,
    candidates_failed: 0,
    candidates_infeasible: 0,
    observations_committed: 3,
    trials_finalized: 3,
    work_units_done: 9,
    work_units_total: 9,
  },
  created_at: NOW,
  updated_at: NOW,
  last_event_id: 14,
};

const STATUS_RUNNING: ExperimentStatusView = {
  ...STATUS_SIMULATED,
  experiment_id: "exp-demo-running",
  state: "running",
  stage: "screening",
  revision: 9,
  last_event_id: 9,
  counters: {
    candidates_proposed: 2,
    candidates_completed: 1,
    candidates_failed: 0,
    candidates_infeasible: 0,
    observations_committed: 1,
    trials_finalized: 1,
    work_units_done: 3,
    work_units_total: 12,
  },
};

const BASELINE: CandidateSpec = {
  candidate_id: "cand-demo-baseline",
  study_id: "study-demo",
  experiment_id: "exp-demo-simulated",
  trial_number: 0,
  engine_id: "llamacpp",
  engine_sha256: SHA,
  model_digest: SHA,
  worker_id: "lab-worker-1",
  context: 4096,
  role: "baseline",
  parameters: { gpu_layers: -1, flash_attn: "auto", threads: 8 },
  workload_digest: SHA,
  state: "finalized",
};

const CANDIDATE: CandidateSpec = {
  ...BASELINE,
  candidate_id: "cand-demo-1",
  trial_number: 1,
  role: "candidate",
  context: 4096,
  parameters: { gpu_layers: -1, flash_attn: "on", threads: 12, batch_size: 1024 },
  state: "finalized",
};

const OBS_BASELINE: BenchmarkObservation = {
  observation_id: "obs-demo-baseline",
  experiment_id: "exp-demo-simulated",
  study_id: "study-demo",
  candidate_id: BASELINE.candidate_id!,
  trial_number: 0,
  worker_id: "lab-worker-1",
  engine_id: "llamacpp",
  engine_sha256: SHA,
  model_digest: SHA,
  workload_digest: SHA,
  context: 4096,
  evidence_kind: "simulated",
  measurement_status: "simulated",
  status: "completed",
  configured_context: 4096,
  effective_context: 4096,
  input_tokens: 3_600,
  output_tokens: 256,
  repetitions: 3,
  samples: [
    { prefill_tokens_per_sec: 1_120, decode_tokens_per_sec: 42.1, time_to_first_token_ms: 88 },
    { prefill_tokens_per_sec: 1_130, decode_tokens_per_sec: 42.4, time_to_first_token_ms: 87 },
    { prefill_tokens_per_sec: 1_125, decode_tokens_per_sec: 42.2, time_to_first_token_ms: 88 },
  ],
  metrics: {
    prefill_tokens_per_sec: 1_125,
    decode_tokens_per_sec: 42.2,
    time_to_first_token_ms: 88,
    total_latency_ms: 6_150,
    gpu_vram_peak_bytes: 5_368_709_120,
    gpu_utilization: 0.94,
  },
  simulated: true,
  quality_gates: [
    { name: "context_truncation", status: "passed" },
    { name: "planned_prompt_tokens", status: "passed" },
  ],
};

const OBS_CANDIDATE: BenchmarkObservation = {
  ...OBS_BASELINE,
  observation_id: "obs-demo-1",
  candidate_id: CANDIDATE.candidate_id!,
  trial_number: 1,
  samples: [
    { prefill_tokens_per_sec: 1_260, decode_tokens_per_sec: 47.8, time_to_first_token_ms: 79 },
    { prefill_tokens_per_sec: 1_270, decode_tokens_per_sec: 48.1, time_to_first_token_ms: 78 },
    { prefill_tokens_per_sec: 1_265, decode_tokens_per_sec: 47.9, time_to_first_token_ms: 79 },
  ],
  metrics: {
    ...OBS_BASELINE.metrics,
    prefill_tokens_per_sec: 1_265,
    decode_tokens_per_sec: 47.9,
    time_to_first_token_ms: 79,
    gpu_vram_peak_bytes: 5_570_516_992,
  },
};

const EVALUATION_SIMULATED: ContextEvaluation = {
  candidate_id: CANDIDATE.candidate_id!,
  context: 4096,
  baseline_candidate_id: BASELINE.candidate_id!,
  baseline_observation_id: OBS_BASELINE.observation_id!,
  observation_id: OBS_CANDIDATE.observation_id!,
  score: 1.128,
  improvement_pct: 12.8,
  interval: {
    confidence_level: 0.95,
    lower: 1.04,
    upper: 1.21,
    point_estimate: 1.128,
    resamples: 2000,
    sample_count: 3,
    method: "paired_log_ratio_bootstrap_percentile",
  },
  qualified: false,
  status: "ineligible",
  reasons: ["SIMULATED_EVIDENCE"],
  baseline_samples: 3,
  candidate_samples: 3,
  simulated: true,
};

const FINAL_SIMULATED: FinalizationResult = {
  experiment_id: "exp-demo-simulated",
  objective: "balanced",
  recipe_mode: "per_context",
  classification: "SIMULATED",
  per_context: [
    {
      context: 4096,
      baseline_candidate_id: BASELINE.candidate_id!,
      winner_candidate_id: null,
      evaluations: [EVALUATION_SIMULATED],
    },
    {
      context: 8192,
      baseline_candidate_id: null,
      winner_candidate_id: null,
      evaluations: [],
    },
  ],
  cross_context: [
    {
      candidate_id: CANDIDATE.candidate_id!,
      contexts: [4096],
      per_context_scores: [1.128],
      score: 1.128,
      complete_coverage: false,
      qualified: false,
      reasons: ["INCOMPLETE_CONTEXT_COVERAGE"],
    },
  ],
  validated_winner_candidate_id: null,
  simulated: true,
  warnings: [
    "SIMULATED_RESULTS_NOT_VALIDATED_FOR_DEPLOYMENT",
    "INCOMPLETE_CROSS_CONTEXT_COVERAGE",
  ],
  threshold_pct: 5,
  confidence_level: 0.95,
};

const FINAL_NO_WINNER: FinalizationResult = {
  ...FINAL_SIMULATED,
  classification: "NO_VALIDATED_WINNER",
  simulated: false,
  warnings: ["NO_VALIDATED_WINNER", "INCOMPLETE_CROSS_CONTEXT_COVERAGE"],
  per_context: [
    {
      ...FINAL_SIMULATED.per_context![0]!,
      evaluations: [
        {
          ...EVALUATION_SIMULATED,
          simulated: false,
          status: "inconclusive",
          score: 1.031,
          improvement_pct: 3.1,
          interval: {
            ...EVALUATION_SIMULATED.interval!,
            lower: 0.94,
            upper: 1.11,
            point_estimate: 1.031,
          },
          reasons: ["BELOW_MINIMUM_IMPROVEMENT", "CONFIDENCE_INTERVAL_NOT_ABOVE_BASELINE"],
        },
      ],
    },
  ],
};

const OBS_SIMULATED_VIEW: BenchmarkObservation = {
  ...OBS_CANDIDATE,
  simulated: true,
  evidence_kind: "simulated",
  measurement_status: "simulated",
};

export const DEMO_VIEW_SIMULATED: ExperimentView = {
  status: STATUS_SIMULATED,
  spec: PLAN.spec,
  plan: PLAN,
  candidates: [BASELINE, CANDIDATE],
  observations: [OBS_BASELINE, OBS_SIMULATED_VIEW],
  feasibility: PLAN.feasibility,
  simulation: true,
  warnings: ["DEMO_DATA: offline fixtures, not measured engine evidence."],
  created_at: NOW,
  completed_at: NOW,
};

export const DEMO_VIEW_RUNNING: ExperimentView = {
  ...DEMO_VIEW_SIMULATED,
  status: STATUS_RUNNING,
  candidates: [BASELINE],
  observations: [OBS_BASELINE],
  completed_at: null,
};

export const DEMO_RESULTS_SIMULATED: ExperimentResultsResponse = {
  experiment_id: "exp-demo-simulated",
  status: STATUS_SIMULATED,
  candidates: [BASELINE, CANDIDATE],
  observations: [OBS_BASELINE, OBS_SIMULATED_VIEW],
  best_candidate_id: CANDIDATE.candidate_id!,
  validated_winner_candidate_id: null,
  finalization: FINAL_SIMULATED,
  simulated: true,
  warnings: FINAL_SIMULATED.warnings,
  phase: "phase-5-finalization",
};

export const DEMO_RESULTS_NO_WINNER: ExperimentResultsResponse = {
  ...DEMO_RESULTS_SIMULATED,
  experiment_id: "exp-demo-no-winner",
  finalization: FINAL_NO_WINNER,
  simulated: false,
  warnings: FINAL_NO_WINNER.warnings,
};

export const DEMO_RECIPE: RecipeView = {
  recipe_id: "recipe-demo-1",
  experiment_id: "exp-demo-validated",
  candidate_id: "cand-demo-validated",
  recipe_digest: SHA,
  status: "validated",
  created_at: NOW,
  recipe: {
    schema_version: "1.0.0",
    engine: {
      id: "llamacpp",
      version: "0.7.0-dev",
      build: "701",
      executable: "/home/pouya/ai-lab/Inference/llama.cpp/build/bin/llama-server",
      sha256: SHA,
      source_commit: "dd002b91f",
    },
    model: {
      id: MODEL.model_id,
      artifact_digest: SHA,
      files: [{ path: "qwen2.5-7b-instruct-q4_k_m.gguf", sha256: SHA, size_bytes: 4_683_000_000 }],
    },
    hardware: {
      gpu_model: "NVIDIA GeForce RTX 3060",
      gpu_uuid: GPU.uuid,
      min_vram_bytes: 6_442_450_944,
    },
    launch: {
      executable: "/home/pouya/ai-lab/Inference/llama.cpp/build/bin/llama-server",
      argv: [
        "--model",
        "/home/pouya/ai-lab/models/qwen2.5-7b-instruct-q4_k_m.gguf",
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
        "--ctx-size",
        "8192",
        "--n-gpu-layers",
        "-1",
        "--flash-attn",
        "on",
        "--threads",
        "12",
      ],
      env: { LD_LIBRARY_PATH: "/home/pouya/ai-lab/Inference/llama.cpp/build/bin" },
      bind_host: "127.0.0.1",
    },
    constraints: {
      require_full_context_proof: true,
      min_improvement_pct: 5,
      confidence_level: 0.95,
    },
    validation: {
      validated: true,
      confidence_ref: "experiments/exp-demo-validated/candidates/cand-demo-validated/qualification.json",
      metrics_ref: "experiments/exp-demo-validated/candidates/cand-demo-validated/metrics.json",
    },
    notes: [
      "DEMO DATA: this recipe is a fixture, not a real validated deployment artifact.",
      "Objective ratio 1.1280; 95% paired interval [1.0800, 1.1900].",
    ],
  },
};

export const DEMO_STATUS: SystemStatusResponse = {
  service: "lab-controller",
  version: "0.1.0",
  api_version: "v1",
  environment: "demo",
  controller_db: "controller.sqlite3",
  optimizer_db: "optimizer.sqlite3",
  scheduler_running: true,
  workers_online: 1,
  experiments_active: 1,
  allow_simulation: true,
  optimizer: {
    status: "ready",
    online: true,
    last_seen_at: NOW,
    studies_open: 3,
    version: "0.1.0",
  },
  warnings: ["DEMO DATA: no controller connection is active."],
};

export const DEMO_RESULTS_VALIDATED: ExperimentResultsResponse = {
  ...DEMO_RESULTS_SIMULATED,
  experiment_id: "exp-demo-validated",
  finalization: {
    ...FINAL_SIMULATED,
    experiment_id: "exp-demo-validated",
    classification: "VALIDATED_WINNER",
    simulated: false,
    warnings: [],
    validated_winner_candidate_id: "cand-demo-validated",
    per_context: [
      {
        context: 4096,
        baseline_candidate_id: "cand-demo-baseline",
        winner_candidate_id: "cand-demo-validated",
        evaluations: [
          {
            ...EVALUATION_SIMULATED,
            candidate_id: "cand-demo-validated",
            simulated: false,
            qualified: true,
            status: "validated",
            reasons: [],
            score: 1.128,
            improvement_pct: 12.8,
          },
        ],
      },
    ],
  },
  simulated: false,
  warnings: [],
};

export const DEMO_EXPERIMENTS = [STATUS_SIMULATED, STATUS_RUNNING];

export const DEMO_PLANS: ExperimentPlan[] = [PLAN];

export type MockApi = {
  status(): Promise<SystemStatusResponse>;
  workers(): Promise<WorkerListResponse>;
  workerSnapshot(workerId: string): Promise<WorkerSnapshot>;
  experiments(): Promise<{ total: number; experiments: ExperimentStatusView[] }>;
  experiment(experimentId: string): Promise<ExperimentView>;
  plan(request: PlanRequest): Promise<PlanResponse>;
  createExperiment(plan: ExperimentPlan): Promise<ExperimentView>;
  pause(experimentId: string): Promise<ExperimentView>;
  resume(experimentId: string): Promise<ExperimentView>;
  cancel(experimentId: string): Promise<ExperimentView>;
  retryPreflight(experimentId: string): Promise<ExperimentView>;
  results(experimentId: string): Promise<ExperimentResultsResponse>;
  recipes(): Promise<{ total: number; recipes: RecipeView[] }>;
  recipe(recipeId: string): Promise<RecipeView>;
  createRecipe(experimentId: string, candidateId: string): Promise<RecipeView>;
  verifyRecipe(recipeId: string): Promise<Record<string, unknown>>;
  promoteRecipe(recipeId: string, body: { target_slot: string; dry_run: boolean }): Promise<Record<string, unknown>>;
  releases(): Promise<ReleaseListResponse>;
  release(noticeId: string): Promise<ReleaseDetailResponse>;
  checkRelease(body: ReleaseCheckRequest): Promise<ReleaseCheckResponse>;
  decideRelease(
    noticeId: string,
    body: { action: "pin" | "defer"; note?: string },
  ): Promise<ReleaseDetailResponse>;
  comparisons(noticeId?: string): Promise<ComparisonListResponse>;
  createComparison(body: ComparisonCreateRequest): Promise<ComparisonPlan>;
  submitComparisonEvidence(
    comparisonId: string,
    body: ComparisonEvidenceRequest,
  ): Promise<ComparisonPlan>;
  subscribeEvents(
    experimentId: string,
    lastEventId: number,
    onEvent: (event: string, id: number | null, data: unknown) => void,
  ): () => void;
  saveReport(): Promise<{ canceled: boolean; path?: string }>;
};

function createDefaultMockApi(): MockApi {
  const views = new Map<string, ExperimentView>([
    ["exp-demo-simulated", structuredClone(DEMO_VIEW_SIMULATED)],
    ["exp-demo-running", structuredClone(DEMO_VIEW_RUNNING)],
    ["exp-demo-no-winner", structuredClone(DEMO_VIEW_SIMULATED)],
    ["exp-demo-validated", structuredClone(DEMO_VIEW_SIMULATED)],
  ]);
  const releaseNotices = new Map(
    DEMO_RELEASES.notices.map((notice) => [notice.notice_id, structuredClone(notice)]),
  );
  const releaseAssessments = new Map(
    Object.entries(DEMO_ASSESSMENTS).map(([noticeId, assessments]) => [
      noticeId,
      structuredClone(assessments),
    ]),
  );
  const comparisonPlans = new Map(
    DEMO_COMPARISONS.comparisons.map((comparison) => [
      comparison.comparison_id,
      structuredClone(comparison),
    ]),
  );

  const releaseDetail = (noticeId: string): ReleaseDetailResponse => {
    const notice = releaseNotices.get(noticeId);
    if (!notice) throw new Error(`release notice not found: ${noticeId}`);
    return structuredClone({
      notice,
      assessments: releaseAssessments.get(noticeId) ?? [],
      comparisons: [...comparisonPlans.values()].filter(
        (comparison) => comparison.notice_id === noticeId,
      ),
    });
  };

  const results = (experimentId: string): ExperimentResultsResponse => {
    if (experimentId === "exp-demo-validated") return structuredClone(DEMO_RESULTS_VALIDATED);
    if (experimentId === "exp-demo-no-winner") return structuredClone(DEMO_RESULTS_NO_WINNER);
    return { ...structuredClone(DEMO_RESULTS_SIMULATED), experiment_id: experimentId };
  };

  const view = (id: string): ExperimentView => {
    const found = views.get(id) ?? views.get("exp-demo-simulated")!;
    return structuredClone(found);
  };

  const eventSnapshot = (experimentId: string): { event: string; data: unknown; id: number } => {
    const current = view(experimentId);
    return {
      event: "snapshot",
      id: current.status.last_event_id ?? 0,
      data: {
        type: "snapshot",
        sequence: current.status.last_event_id ?? 0,
        snapshot: {
          snapshot_sequence: current.status.last_event_id ?? 0,
          status: current.status,
          recent_events: [],
        },
      },
    };
  };

  return {
    async status() {
      return structuredClone(DEMO_STATUS);
    },
    async workers() {
      return structuredClone(DEMO_WORKERS);
    },
    async workerSnapshot() {
      return structuredClone(DEMO_SNAPSHOT);
    },
    async experiments() {
      return { total: DEMO_EXPERIMENTS.length, experiments: structuredClone(DEMO_EXPERIMENTS) };
    },
    async experiment(experimentId) {
      return view(experimentId);
    },
    async plan(request) {
      const contexts = request.contexts;
      const plan: ExperimentPlan = {
        ...structuredClone(PLAN),
        plan_id: "plan-demo-fixture",
        spec: {
          ...structuredClone(PLAN.spec),
          worker_id: request.worker_id,
          contexts,
          objective: request.objective ?? "balanced",
          search_depth: request.search_depth ?? "quick",
          search_policy: (request.search_policy ?? PLAN.spec.search_policy) as SearchPolicy,
          constraints: request.constraints ?? PLAN.spec.constraints,
          recipe_mode: request.recipe_mode ?? "per_context",
          gpu_uuids: request.gpu_uuids ?? [GPU.uuid],
        },
        feasibility: contexts.map((context) => ({
          context,
          status: context >= 65536 ? "resource_infeasible" : "feasible",
          requires_full_context_proof: true,
          estimated_vram_bytes: 5_368_709_120 + context * 131_072,
          evidence: ["DEMO_DATA: static feasibility projection, not measured."],
        })),
        warnings: [
          "DEMO_DATA: offline fixtures, not measured engine evidence.",
          ...(contexts.includes(131072)
            ? ["128K is displayed as a requested analysis target; feasibility is not proven."]
            : []),
        ],
        created_at: new Date().toISOString(),
        stage: "queued",
      };
      return { status: "ready", plan, reason: null };
    },
    async createExperiment(plan) {
      const experimentId = `exp-demo-${Date.now()}`;
      const status: ExperimentStatusView = {
        ...structuredClone(STATUS_RUNNING),
        experiment_id: experimentId,
        state: "queued",
        stage: "queued",
        revision: 1,
        last_event_id: 1,
        counters: {},
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      const created: ExperimentView = {
        ...structuredClone(DEMO_VIEW_RUNNING),
        status,
        spec: plan.spec,
        plan,
        candidates: [],
        observations: [],
        simulation: true,
        warnings: ["DEMO_DATA: no controller request was made."],
        created_at: new Date().toISOString(),
        completed_at: null,
      };
      views.set(experimentId, created);
      DEMO_EXPERIMENTS.unshift(status);
      return structuredClone(created);
    },
    async pause(experimentId) {
      const current = view(experimentId);
      current.status = { ...current.status, state: "paused", paused: true };
      views.set(experimentId, current);
      return current;
    },
    async resume(experimentId) {
      const current = view(experimentId);
      current.status = { ...current.status, state: "running", paused: false };
      views.set(experimentId, current);
      return current;
    },
    async cancel(experimentId) {
      const current = view(experimentId);
      current.status = { ...current.status, state: "cancelled", stage: "completed" };
      views.set(experimentId, current);
      return current;
    },
    async retryPreflight(experimentId) {
      const current = view(experimentId);
      current.status = { ...current.status, state: "queued", stage: "preflight" };
      views.set(experimentId, current);
      return current;
    },
    async results(experimentId) {
      return results(experimentId);
    },
    async recipes() {
      return { total: 1, recipes: [structuredClone(DEMO_RECIPE)] };
    },
    async recipe() {
      return structuredClone(DEMO_RECIPE);
    },
    async createRecipe(experimentId, candidateId) {
      return {
        ...structuredClone(DEMO_RECIPE),
        recipe_id: `recipe-demo-${Date.now()}`,
        experiment_id: experimentId,
        candidate_id: candidateId,
      };
    },
    async verifyRecipe() {
      return {
        recipe_id: DEMO_RECIPE.recipe_id,
        verified: false,
        message: "DEMO_DATA: verification requires a real worker and is not simulated here.",
        checks: [
          { name: "binary_hash", status: "not_run", detail: "No worker command was issued in demo mode." },
          { name: "model_hash", status: "not_run", detail: "No worker command was issued in demo mode." },
        ],
      };
    },
    async promoteRecipe() {
      return {
        promoted: false,
        dry_run: true,
        message: "DEMO_DATA: promotion is a guarded operator action and is disabled in demo mode.",
      };
    },
    async releases() {
      const notices = [...releaseNotices.values()];
      return structuredClone({ total: notices.length, notices });
    },
    async release(noticeId) {
      return releaseDetail(noticeId);
    },
    async checkRelease(body) {
      const release = body.release;
      const existing = [...releaseNotices.values()].find(
        (notice) =>
          notice.release.version === release.version &&
          notice.release.build === release.build,
      );
      if (existing) {
        const assessment = releaseAssessments.get(existing.notice_id)?.[0];
        if (!assessment) throw new Error("demo assessment is missing");
        return structuredClone({
          result: "reused",
          notice: existing,
          assessment,
        });
      }

      const changedPaths = release.changed_paths ?? [];
      const docsOnly =
        changedPaths.length > 0 &&
        changedPaths.every(
          (path) => path.startsWith("docs/") || path.startsWith("documentation/"),
        );
      const alreadyInstalled =
        release.version === BASELINE_ENGINE.version &&
        release.build === BASELINE_ENGINE.build &&
        release.artifact_sha256 === BASELINE_ENGINE.executable_sha256;
      const cudaArea = changedPaths.some(
        (path) => path.includes("cuda") || path.includes("ggml"),
      );
      const impact = alreadyInstalled || docsOnly ? "P2" : cudaArea ? "P0" : "P1";
      const applicable = !alreadyInstalled;
      const requiresComparison = applicable && impact !== "P2";
      const slug = `${release.version}-${release.build}`.replace(/[^a-zA-Z0-9_.-]/g, "-");
      const noticeId = `rel-demo-${slug}`;
      const assessmentId = `impact-demo-${slug}`;
      const reasons = [
        ...(alreadyInstalled ? ["RELEASE_ALREADY_INSTALLED"] : []),
        ...(docsOnly ? ["DOCUMENTATION_ONLY"] : []),
        ...(impact === "P0" ? ["P0_RELEASE_AREA"] : []),
        ...(impact === "P1" ? ["IMPACT_UNCERTAIN_REQUIRES_SMOKE"] : []),
      ];
      const notice: ReleaseNoticeView = {
        notice_id: noticeId,
        release: structuredClone(release),
        metadata_digest: release.artifact_sha256 ?? SHA,
        imported_at: new Date().toISOString(),
        decision: "pending",
      };
      const assessment: ImpactAssessment = {
        assessment_id: assessmentId,
        notice_id: noticeId,
        worker_id: body.worker_id,
        model_id: body.model_id ?? MODEL.model_id,
        model_digest: MODEL_DIGEST,
        model_identity_complete: true,
        engine_id: release.engine_id,
        current_engine: BASELINE_ENGINE,
        candidate_engine_sha256: release.artifact_sha256 ?? null,
        inventory_digest: SHA,
        inventory_snapshot_revision: 4,
        inventory_fresh: true,
        gpu_uuids: [GPU.uuid],
        impact,
        applicable,
        requires_smoke: requiresComparison,
        requires_ab: requiresComparison,
        recommended_action: requiresComparison ? "targeted_rerun" : "ignore",
        reasons,
        changed_areas: docsOnly ? ["documentation"] : ["cuda_kernel", "kv_cache"],
        capability_diff: { added: [], removed: [], changed: [], impact_class: impact },
      };
      releaseNotices.set(noticeId, notice);
      releaseAssessments.set(noticeId, [assessment]);
      return structuredClone({
        result: alreadyInstalled ? "already_installed" : "imported",
        notice,
        assessment,
      } satisfies ReleaseCheckResponse);
    },
    async decideRelease(noticeId, body) {
      const notice = releaseNotices.get(noticeId);
      if (!notice) throw new Error(`release notice not found: ${noticeId}`);
      notice.decision = body.action === "pin" ? "pinned" : "deferred";
      notice.decision_note = body.note ?? null;
      notice.decision_at = new Date().toISOString();
      return releaseDetail(noticeId);
    },
    async comparisons(noticeId) {
      const comparisons = [...comparisonPlans.values()].filter(
        (comparison) => !noticeId || comparison.notice_id === noticeId,
      );
      return structuredClone({ total: comparisons.length, comparisons });
    },
    async createComparison(body) {
      const detail = releaseDetail(body.notice_id);
      const assessment = detail.assessments?.find(
        (item) => item.assessment_id === body.assessment_id,
      );
      if (!assessment) throw new Error("demo assessment not found");
      if (!assessment.requires_ab) {
        throw new Error("release does not require an A/B comparison");
      }
      const comparisonId = `cmp-demo-${Date.now()}`;
      const candidate: EngineIdentity = {
        ...BASELINE_ENGINE,
        version: detail.notice.release.version,
        build: detail.notice.release.build,
        executable_sha256: assessment.candidate_engine_sha256 ?? CANDIDATE_SHA,
        source_commit: detail.notice.release.source_commit ?? null,
        source_digest: assessment.candidate_engine_sha256 ?? CANDIDATE_SHA,
      };
      const plan: ComparisonPlan = {
        comparison_id: comparisonId,
        notice_id: body.notice_id,
        assessment_id: body.assessment_id,
        worker_id: assessment.worker_id,
        model_id: assessment.model_id ?? MODEL.model_id,
        model_digest: assessment.model_digest ?? MODEL_DIGEST,
        baseline_engine: assessment.current_engine ?? BASELINE_ENGINE,
        candidate_engine: candidate,
        contexts: body.contexts,
        objective: body.objective ?? "balanced",
        min_improvement_pct: body.min_improvement_pct ?? 5,
        confidence_level: body.confidence_level ?? 0.95,
        gpu_uuids: assessment.gpu_uuids ?? [GPU.uuid],
        workload: body.workload,
        status: "awaiting_evidence",
        result: null,
        evidence_digest: null,
        created_at: new Date().toISOString(),
        evaluated_at: null,
      };
      comparisonPlans.set(comparisonId, plan);
      detail.notice.decision = "comparison_requested";
      return structuredClone(plan);
    },
    async submitComparisonEvidence(comparisonId, body) {
      const plan = comparisonPlans.get(comparisonId);
      if (!plan) throw new Error(`comparison not found: ${comparisonId}`);
      const simulated = body.simulated || body.measurement_status === "simulated";
      const contextResults = simulated
        ? []
        : (body.samples ?? []).map((sample) => {
            const baseline = (sample.baseline.prefill_tokens_per_sec + sample.baseline.decode_tokens_per_sec) / 2;
            const candidate = (sample.candidate.prefill_tokens_per_sec + sample.candidate.decode_tokens_per_sec) / 2;
            const ratio = baseline > 0 ? candidate / baseline : 1;
            const status: "improved" | "regressed" | "inconclusive" =
              ratio >= 1.05 ? "improved" : ratio <= 0.95 ? "regressed" : "inconclusive";
            return {
              context: sample.context,
              status,
              sample_count: 3,
              score: ratio,
              improvement_pct: (ratio - 1) * 100,
              interval: {
                confidence_level: 0.95,
                method: "paired_percentile_bootstrap",
                point_estimate: ratio,
                lower: ratio - 0.02,
                upper: status === "regressed" ? ratio - 0.005 : ratio + 0.02,
                resamples: 10_000,
                sample_count: 3,
              },
              reasons: status === "improved" ? [] : [status.toUpperCase()],
            };
          });
      const overall = simulated
        ? "incompatible"
        : contextResults.length > 0 && contextResults.every((item) => item.status === "improved")
          ? "improved"
          : contextResults.some((item) => item.status === "regressed")
            ? "regressed"
            : "inconclusive";
      const result: ComparisonResult = {
        comparison_id: comparisonId,
        status: overall,
        objective: plan.objective,
        min_improvement_pct: plan.min_improvement_pct ?? 5,
        confidence_level: plan.confidence_level ?? 0.95,
        evaluated_at: new Date().toISOString(),
        upgrade_approved: false,
        recommendation: overall === "improved" ? "review_candidate" : "keep_current",
        reasons: simulated
          ? ["SIMULATED_EVIDENCE"]
          : contextResults.flatMap((item) =>
              (item.reasons ?? []).map((reason) => `${item.context}:${reason}`),
            ),
        contexts: contextResults,
      };
      plan.status = overall;
      plan.result = result;
      plan.evidence_digest = SHA;
      plan.evaluated_at = result.evaluated_at;
      return structuredClone(plan);
    },
    subscribeEvents(experimentId, _lastEventId, onEvent) {
      const snapshot = eventSnapshot(experimentId);
      const timer = setTimeout(() => onEvent(snapshot.event, snapshot.id, snapshot.data), 10);
      return () => clearTimeout(timer);
    },
    async saveReport() {
      return { canceled: false, path: "demo://report.json" };
    },
  };
}


/** Explicit offline QA scenarios. These never wrap the real IPC client. */
export const DEMO_SCENARIOS = ["default", "stale", "partial", "empty", "error", "stream-gap", "large", "failed"] as const;
export function createMockApi(scenario = "default"): MockApi {
  const base = createDefaultMockApi();
  if (!DEMO_SCENARIOS.includes(scenario as typeof DEMO_SCENARIOS[number])) return base;
  const unreachable = async (): Promise<never> => { throw new Error("DEMO fixture: controller request unavailable (no service contacted)"); };
  if (scenario === "error") return { ...base, status: unreachable, workers: unreachable, experiments: unreachable, recipes: unreachable, releases: unreachable };
  if (scenario === "empty") return { ...base,
    workers: async () => ({ workers: [], total: 0 }), experiments: async () => ({ experiments: [], total: 0 }),
    recipes: async () => ({ recipes: [], total: 0 }), releases: async () => ({ notices: [], total: 0 }),
  };
  if (scenario === "stale") return { ...base,
    plan: async () => ({ status: "preflight_required", command_id: "cmd-demo-stale-snapshot", reason: "SNAPSHOT_STALE: offline fixture; cached inventory must be refreshed", retry_after_ms: 30_000 }),
  };
  if (scenario === "stream-gap") return { ...base,
    subscribeEvents: (_id, _after, onEvent) => { const timer = setTimeout(() => onEvent("event.gap", null, { reason: "DEMO: replay floor exceeded" }), 10); return () => clearTimeout(timer); },
  };
  if (scenario === "partial" || scenario === "large" || scenario === "failed") {
    const prepare = async (id: string) => {
      const original = await base.experiment(id);
      if (scenario === "failed") return { ...original,
        status: { ...original.status, state: "failed" as const, error_code: "OOM", error_message: "DEMO: insufficient memory; no valid measurement" },
        observations: (original.observations ?? []).map(item => ({ ...item, metrics: {}, samples: [], measurement_status: "invalid" as const, failure: {kind:"OOM" as const, stage:"unknown" as const,message:"DEMO: memory allocation failed",retryable:false} })),
      };
      if (scenario === "partial") return { ...original,
        observations: (original.observations ?? []).map(item => ({ ...item, metrics: {}, samples: [], measurement_status: "unavailable" as const })),
      };
      return { ...original,
        candidates: Array.from({ length: 5000 }, (_, index) => ({ ...CANDIDATE, candidate_id: `cand-demo-large-${index}`, trial_number: index })),
        observations: Array.from({ length: 5000 }, (_, index) => ({ ...OBS_SIMULATED_VIEW, observation_id: `obs-demo-large-${index}`, candidate_id: `cand-demo-large-${index}`, trial_number: index })),
      };
    };
    return { ...base, experiment: prepare, results: async id => {
      const original = await base.results(id), evidence = await prepare(id);
      return { ...original, candidates: evidence.candidates, observations: evidence.observations };
    } };
  }
  return base;
}
