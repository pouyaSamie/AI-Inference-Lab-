import { useCallback, useEffect, useMemo, useState } from "react";
import { createLabApi, setDemoRequested } from "./lib/api";
import type { LabApi } from "./lib/api";
import { usePolling } from "./lib/hooks";
import { Badge, StatusBadge } from "./components/ui";
import { OverviewPage } from "./pages/OverviewPage";
import { ModelsPage } from "./pages/ModelsPage";
import { EnginesPage } from "./pages/EnginesPage";
import { WorkersPage } from "./pages/WorkersPage";
import { OptimizePage } from "./pages/OptimizePage";
import { LiveRunsPage } from "./pages/LiveRunsPage";
import { ComparePage } from "./pages/ComparePage";
import { RecipesPage } from "./pages/RecipesPage";
import { UpdatesPage } from "./pages/UpdatesPage";
import { SettingsPage } from "./pages/SettingsPage";
import type { PageId, PageProps } from "./pages/types";

const NAV: { id: PageId; label: string; glyph: string }[] = [
  { id: "overview", label: "Overview", glyph: "◉" },
  { id: "models", label: "Models", glyph: "▤" },
  { id: "engines", label: "Engines", glyph: "⌘" },
  { id: "workers", label: "Workers", glyph: "▣" },
  { id: "optimize", label: "Optimize", glyph: "⌁" },
  { id: "live", label: "Live Runs", glyph: "◌" },
  { id: "compare", label: "Compare", glyph: "≋" },
  { id: "recipes", label: "Recipes", glyph: "▧" },
  { id: "updates", label: "Updates", glyph: "↑" },
  { id: "settings", label: "Settings", glyph: "⚙" },
];

const PAGE_TITLES: Record<PageId, string> = {
  overview: "Overview",
  models: "Models",
  engines: "Engines",
  workers: "Workers",
  optimize: "Optimize",
  live: "Live Runs",
  compare: "Compare",
  recipes: "Recipes",
  updates: "Updates",
  settings: "Settings",
};

function pageFromHash(): PageId {
  const raw = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  return NAV.some((item) => item.id === raw) ? (raw as PageId) : "overview";
}

export function App() {
  const [api, setApi] = useState<LabApi>(() => createLabApi());
  const [page, setPage] = useState<PageId>(() => pageFromHash());
  const [activeExperimentId, setActiveExperimentId] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
    return params.get("experiment");
  });

  const statusPoll = usePolling(() => api.status(), 15_000);
  const experimentsPoll = usePolling(() => api.experiments(50), 8_000);

  const navigate = useCallback((next: PageId, experimentId?: string) => {
    setPage(next);
    if (experimentId !== undefined) setActiveExperimentId(experimentId);
    const query = experimentId ? `?experiment=${encodeURIComponent(experimentId)}` : "";
    window.location.hash = `#/${next}${query}`;
  }, []);

  useEffect(() => {
    const onHash = () => {
      setPage(pageFromHash());
      const params = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
      setActiveExperimentId(params.get("experiment"));
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    document.title = `AI Inference Optimization Lab · ${PAGE_TITLES[page]}`;
  }, [page]);

  useEffect(() => {
    statusPoll.refresh();
    experimentsPoll.refresh();
  }, [api, experimentsPoll.refresh, statusPoll.refresh]);

  const toggleDemo = useCallback((enabled: boolean) => {
    setDemoRequested(enabled);
    setActiveExperimentId(null);
    setApi(createLabApi());
  }, []);

  const refreshShell = useCallback(() => {
    statusPoll.refresh();
    experimentsPoll.refresh();
  }, [experimentsPoll, statusPoll]);

  const props = useMemo<PageProps>(
    () => ({
      api,
      status: statusPoll.data,
      statusError: statusPoll.error,
      experiments: experimentsPoll.data,
      experimentsError: experimentsPoll.error,
      activeExperimentId,
      setActiveExperimentId,
      navigate,
      refreshShell,
    }),
    [
      activeExperimentId,
      api,
      experimentsPoll.data,
      experimentsPoll.error,
      navigate,
      refreshShell,
      statusPoll.data,
      statusPoll.error,
    ],
  );

  const connection = statusPoll.error
    ? { tone: "danger" as const, label: "Controller unreachable" }
    : statusPoll.data
      ? { tone: "ok" as const, label: "Controller online" }
      : { tone: "warn" as const, label: "Connecting" };

  return (
    <div className="app-frame">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">AI</div>
          <div>
            <strong>Inference Lab</strong>
            <span>Local optimization</span>
          </div>
        </div>
        <nav aria-label="Primary">
          {NAV.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${page === item.id ? "active" : ""}`}
              onClick={() => navigate(item.id)}
              aria-current={page === item.id ? "page" : undefined}
            >
              <span className="nav-glyph" aria-hidden="true">
                {item.glyph}
              </span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <Badge tone={api.demo ? "simulated" : "info"}>{api.demo ? "DEMO DATA" : "LIVE BACKEND"}</Badge>
          <span>Jobs are owned by the controller and worker, never this window.</span>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div>
            <span className="topbar-page">{PAGE_TITLES[page]}</span>
            <span className="topbar-sub">Local-first controller console</span>
          </div>
          <div className="topbar-right">
            <span className={`connection connection-${connection.tone}`}>
              <span className="connection-dot" aria-hidden="true" />
              {connection.label}
            </span>
            {statusPoll.data?.optimizer?.online ? (
              <StatusBadge value="optimizer online" />
            ) : (
              <Badge tone={statusPoll.data ? "warn" : "neutral"}>
                {statusPoll.data ? "Optimizer offline" : "Optimizer unknown"}
              </Badge>
            )}
            <button className="button button-secondary" onClick={refreshShell}>
              Refresh
            </button>
          </div>
        </header>

        {api.demo ? (
          <div className="demo-strip">
            <strong>OFFLINE DEMO MODE</strong>
            <span>
              Every number below is a fixture. No controller, worker, GPU, engine or model is
              contacted. Turn demo mode off in Settings to use the real backend.
            </span>
          </div>
        ) : null}

        <main className="page">
          {page === "overview" ? <OverviewPage {...props} /> : null}
          {page === "models" ? <ModelsPage {...props} /> : null}
          {page === "engines" ? <EnginesPage {...props} /> : null}
          {page === "workers" ? <WorkersPage {...props} /> : null}
          {page === "optimize" ? <OptimizePage {...props} /> : null}
          {page === "live" ? <LiveRunsPage {...props} /> : null}
          {page === "compare" ? <ComparePage {...props} /> : null}
          {page === "recipes" ? <RecipesPage {...props} /> : null}
          {page === "updates" ? <UpdatesPage {...props} /> : null}
          {page === "settings" ? (
            <SettingsPage {...props} demoEnabled={api.demo} onDemoChange={toggleDemo} />
          ) : null}
        </main>
      </div>
    </div>
  );
}
