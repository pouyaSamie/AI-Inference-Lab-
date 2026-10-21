import type {
  ExperimentListResponse,
  ExperimentStatusView,
  SystemStatusResponse,
} from "../lib/contracts";
import type { LabApi } from "../lib/api";

export type PageId =
  | "overview"
  | "models"
  | "engines"
  | "workers"
  | "optimize"
  | "live"
  | "compare"
  | "recipes"
  | "updates"
  | "settings";

export interface PageProps {
  api: LabApi;
  status: SystemStatusResponse | null;
  statusError: unknown;
  experiments: ExperimentListResponse | null;
  experimentsError: unknown;
  activeExperimentId: string | null;
  setActiveExperimentId: (experimentId: string | null) => void;
  navigate: (page: PageId, experimentId?: string) => void;
  refreshShell: () => void;
}

export type ExperimentSummary = ExperimentStatusView;
