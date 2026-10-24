import {
  Activity, ArrowDownToLine, ChartNoAxesCombined, CircleHelp, Cpu, Database,
  LayoutGrid, Monitor, Moon, NotebookText, RefreshCw, Server, Settings2,
  SlidersHorizontal, Sun,
} from "lucide-react";

const icons = {
  sun: Sun, moon: Moon, system: Monitor, refresh: RefreshCw,
  overview: LayoutGrid, models: Database, engines: Cpu, workers: Server,
  optimize: SlidersHorizontal, live: Activity, compare: ChartNoAxesCombined,
  recipes: NotebookText, updates: ArrowDownToLine, settings: Settings2, help: CircleHelp,
} as const;
export type WorkstationIconName = keyof typeof icons;

/** One locally bundled icon family, optical size and stroke for all shell controls. */
export function WorkstationIcon({ name }: { name: WorkstationIconName }) {
  const Icon = icons[name];
  return <Icon size={18} strokeWidth={1.75} aria-hidden="true" focusable="false" />;
}
