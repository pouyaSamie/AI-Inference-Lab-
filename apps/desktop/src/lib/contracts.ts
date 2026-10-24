import type { components, operations, paths } from "../../../../packages/client-contracts/src/openapi-types";

export type { components, operations, paths };

export type Schemas = components["schemas"];
export type ExperimentView = Schemas["ExperimentView"];
export type ExperimentStatusView = Schemas["ExperimentStatusView"];
export type ExperimentResultsResponse = Schemas["ExperimentResultsResponse"];
export type ExperimentPlan = Schemas["ExperimentPlan"];
export type ExperimentSpec = Schemas["ExperimentSpec"];
export type PlanRequest = Schemas["PlanRequest"];
export type PlanResponse = Schemas["PlanResponse"];
export type FinalizationResult = Schemas["FinalizationResult"];
export type ContextRanking = Schemas["ContextRanking"];
export type ContextEvaluation = Schemas["ContextEvaluation"];
export type CrossContextRanking = Schemas["CrossContextRanking"];
export type BenchmarkObservation = Schemas["BenchmarkObservation"];
export type CandidateSpec = Schemas["CandidateSpec"];
export type CandidateRole = Schemas["CandidateRole"];
export type WorkerListResponse = Schemas["WorkerListResponse"];
export type WorkerView = Schemas["WorkerView"];
export type CommandStatusView = Schemas["CommandStatusView"];
export type WorkerSnapshot = Schemas["WorkerSnapshot"];
export type EngineIdentity = Schemas["EngineIdentity"];
export type EngineCapabilityManifest = Schemas["EngineCapabilityManifest"];
export type ModelArtifact = Schemas["ModelArtifact"];
export type GPUDevice = Schemas["GPUDevice"];
export type SystemStatusResponse = Schemas["SystemStatusResponse"];
export type ExperimentListResponse = Schemas["ExperimentListResponse"];
export type RecipeListResponse = Schemas["RecipeListResponse"];
export type RecipeView = Schemas["RecipeView"];
export type ReleaseListResponse = Schemas["ReleaseListResponse"];
export type ReleaseDetailResponse = Schemas["ReleaseDetailResponse"];
export type ReleaseCheckRequest = Schemas["ReleaseCheckRequest"];
export type ReleaseCheckResponse = Schemas["ReleaseCheckResponse"];
export type ReleaseNoticeView = Schemas["ReleaseNoticeView"];
export type ReleaseMetadata = Schemas["ReleaseMetadata"];
export type ReleaseDecision = Schemas["ReleaseDecision"];
export type ImpactAssessment = Schemas["ImpactAssessment"];
export type ComparisonPlan = Schemas["ComparisonPlan"];
export type ComparisonResult = Schemas["ComparisonResult"];
export type ComparisonListResponse = Schemas["ComparisonListResponse"];
export type ComparisonCreateRequest = Schemas["ComparisonCreateRequest"];
export type ComparisonEvidenceRequest = Schemas["ComparisonEvidenceRequest"];
export type ComparisonStatus = Schemas["ComparisonStatus"];
export type ImpactClass = Schemas["ImpactClass"];
export type SearchPolicy = Schemas["SearchPolicy"];
export type JobStage = Schemas["JobStage"];
export type JobState = Schemas["JobState"];
export type JobEvent = Schemas["JobEvent"];
export type ContextLength = Schemas["ContextLength"];
export type Objective = Schemas["Objective"];
export type SearchDepth = Schemas["SearchDepth"];
export type RecipeMode = Schemas["RecipeMode"];
export type EventType = Schemas["EventType"];
export type EventPage = Schemas["EventPage"];

export const CONTEXTS: ContextLength[] = [4096, 8192, 16384, 32768, 65536, 131072];
export const OBJECTIVES: { value: Objective; label: string; description: string }[] = [
  {
    value: "balanced",
    label: "Balanced",
    description: "Geometric mean of prefill and decode ratios. The default and most conservative choice.",
  },
  {
    value: "decode_max",
    label: "Generation max",
    description: "Maximize decode tokens per second while keeping the same evidence gates.",
  },
  {
    value: "prefill_max",
    label: "Prefill max",
    description: "Maximize prompt-processing throughput while keeping the same evidence gates.",
  },
];
export const SEARCH_DEPTHS: { value: SearchDepth; label: string; detail: string }[] = [
  { value: "quick", label: "Quick", detail: "12 candidates · screening 2 · 3 replications" },
  { value: "standard", label: "Standard", detail: "36 candidates · finalists 5 · confidence checked" },
  { value: "thorough", label: "Thorough", detail: "96 candidates · broader feasibility exploration" },
];

export const STAGES: JobStage[] = [
  "queued",
  "preflight",
  "baseline",
  "screening",
  "refinement",
  "finalist_validation",
  "report",
  "completed",
];

export const CONTEXT_LABELS: Record<number, string> = {
  4096: "4K",
  8192: "8K",
  16384: "16K",
  32768: "32K",
  65536: "64K",
  131072: "128K",
};

export type RecipeRecord = RecipeView["recipe"];
