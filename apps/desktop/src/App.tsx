import { WorkstationIcon, type WorkstationIconName } from "./components/Icons";
import { ModelVerificationProgress } from "./components/ModelVerification";
import { StartupUpdateSuggestion } from "./components/EngineUpdates";
import { useCallback, useEffect, useMemo, useState } from "react";
import { createLabApi, setDemoRequested } from "./lib/api";
import type { LabApi } from "./lib/api";
import { usePolling } from "./lib/hooks";
import { LocalRuntimePanel, useLocalRuntime } from "./components/LocalRuntime";
import { formatTimestamp } from "./lib/format";
import { Badge, RefreshButton, StatusBadge } from "./components/ui";
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
import { HelpPage } from "./pages/HelpPage";
import type { PageId, PageProps } from "./pages/types";

const NAV: { id: PageId; label: string; glyph: WorkstationIconName }[] = [
  { id: "overview", label: "Overview", glyph: "overview" },
  { id: "models", label: "Models", glyph: "models" },
  { id: "engines", label: "Engines", glyph: "engines" },
  { id: "workers", label: "Workers", glyph: "workers" },
  { id: "optimize", label: "Optimize", glyph: "optimize" },
  { id: "live", label: "Live Runs", glyph: "live" },
  { id: "compare", label: "Compare", glyph: "compare" },
  { id: "recipes", label: "Recipes", glyph: "recipes" },
  { id: "updates", label: "Updates", glyph: "updates" },
  { id: "settings", label: "Settings", glyph: "settings" },
  { id: "help", label: "Help & guide", glyph: "help" },
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
  help: "Help & guide",
};

function pageFromHash(): PageId {
  const raw = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  return NAV.some((item) => item.id === raw) ? (raw as PageId) : "overview";
}

export function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem("lab.theme") ?? "system");
  const [systemDark, setSystemDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  const darkAppearance = theme === "dark" || (theme === "system" && systemDark);
  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setSystemDark(query.matches);
    query.addEventListener("change", update);
    const appearanceChanged = () => setTheme(localStorage.getItem("lab.theme") ?? "system");
    window.addEventListener("lab:appearance-changed", appearanceChanged);
    return () => { query.removeEventListener("change", update); window.removeEventListener("lab:appearance-changed", appearanceChanged); };
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("lab.theme", theme);
    window.dispatchEvent(new Event("lab:appearance-changed"));
  }, [theme]);
  const localRuntime = useLocalRuntime();
  const [setupRequired, setSetupRequired] = useState(() => localStorage.getItem("lab.setup.complete") !== "1");
  useEffect(() => {
    const update = () => setSetupRequired(localStorage.getItem("lab.setup.complete") !== "1");
    window.addEventListener("lab:setup-changed", update);
    return () => window.removeEventListener("lab:setup-changed", update);
  }, []);
  const [api, setApi] = useState<LabApi>(() => createLabApi());
  const [page, setPage] = useState<PageId>(() => pageFromHash());
  const [activeExperimentId, setActiveExperimentId] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
    return params.get("experiment");
  });

  const runtimeBlocking = !api.demo && localRuntime.data && !["ready", "needs_configuration"].includes(localRuntime.data.state);
  const statusPoll = usePolling(() => api.status(), 15_000, !runtimeBlocking, api);
  const experimentsPoll = usePolling(() => api.experiments(50), 8_000, !runtimeBlocking, api);

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
    document.getElementById("main-content")?.focus();
  }, [page]);

  useEffect(() => {
    statusPoll.refresh();
    experimentsPoll.refresh();
  }, [api, experimentsPoll.refresh, statusPoll.refresh]);

  useEffect(() => {
    if (localRuntime.data?.state === "ready" || localRuntime.data?.state === "needs_configuration") {
      statusPoll.refresh(); experimentsPoll.refresh();
    }
  }, [localRuntime.data?.state, statusPoll.refresh, experimentsPoll.refresh]);

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

  const connection = runtimeBlocking
    ? { tone: "warn" as const, label: localRuntime.data?.state === "starting" ? "Starting local lab" : "Local lab needs attention" }
    : statusPoll.error
    ? { tone: "danger" as const, label: "Controller unreachable" }
    : statusPoll.data
      ? { tone: "ok" as const, label: api.demo ? "Fixture data" : "Controller online" }
      : { tone: "warn" as const, label: "Connecting" };

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById("main-content")?.focus(); }}>Skip to workspace</a>
      {!api.demo ? <StartupUpdateSuggestion /> : null}
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
                <WorkstationIcon name={item.glyph} />
              </span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <Badge tone={api.demo ? "simulated" : "info"}>{api.demo ? "DEMO DATA" : "LIVE BACKEND"}</Badge>
          <span>{localRuntime.data?.managed ? "Desktop-managed services: minimize to keep work running. Quit stops the local lab." : "Execution belongs to independent controller and worker services."}</span>
          <span>Last response: {api.demo ? "fixture" : formatTimestamp(statusPoll.lastSuccessAt)}</span>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div>
            <span className="topbar-page">{PAGE_TITLES[page]}</span>
            <span className="topbar-sub">Local-first controller console</span>
          </div>
          <div className="topbar-right">
            <span role="status" className={`connection connection-${connection.tone}`}>
              <span className="connection-dot" aria-hidden="true" />
              {connection.label}
            </span>
            {!statusPoll.error && statusPoll.data?.optimizer?.online ? (
              <StatusBadge value="optimizer online" />
            ) : (
              <Badge tone={statusPoll.data ? "warn" : "neutral"}>
                {statusPoll.data && !statusPoll.error ? "Optimizer offline" : "Optimizer unknown"}
              </Badge>
            )}
            <div className="shell-utilities">
              <button className="icon-button toolbar-icon" role="switch" aria-checked={darkAppearance} aria-label="Dark appearance"
                title={darkAppearance ? "Switch to light theme" : "Switch to dark theme"} onClick={() => setTheme(darkAppearance ? "light" : "dark")}>
                <WorkstationIcon name={darkAppearance ? "moon" : "sun"} />
              </button>
              <RefreshButton onClick={() => window.dispatchEvent(new Event("lab:refresh-page"))} />
            </div>
          </div>
        </header>

        {api.demo ? (
          <div className="demo-strip">
            <strong>OFFLINE DEMO MODE</strong>
            <span className="demo-scenario">{new URLSearchParams(window.location.search).get("demoScenario") ?? "default"} fixture</span>
            <span>
              Every number below is a fixture. No controller, worker, GPU, engine or model is
              contacted. Turn demo mode off in Settings to use the real backend.
            </span>
          </div>
        ) : null}

        <main key={api.demo ? "demo" : "controller"} className="page" id="main-content" tabIndex={-1}>
          {page === "help" ? <HelpPage navigate={navigate} /> : <>
          {!api.demo && localRuntime.data?.state === "ready" && !setupRequired && !["models", "optimize", "settings"].includes(page) ? <ModelVerificationProgress value={localRuntime.data.inventory?.verification} /> : null}
          {runtimeBlocking ? <LocalRuntimePanel /> : <>
          {!api.demo && localRuntime.data && (localRuntime.data.state !== "ready" || setupRequired) && page !== "settings" && page !== "optimize" ? <LocalRuntimePanel /> : null}
          {page === "overview" ? <OverviewPage {...props} /> : null}
          {page === "models" ? <ModelsPage {...props} /> : null}
          {page === "engines" ? <EnginesPage {...props} /> : null}
          {page === "workers" ? <WorkersPage {...props} /> : null}
          {page === "optimize" ? (!api.demo && localRuntime.data && localRuntime.data.state !== "ready" ? <LocalRuntimePanel /> : <OptimizePage {...props} />) : null}
          {page === "live" ? <LiveRunsPage {...props} /> : null}
          {page === "compare" ? <ComparePage {...props} /> : null}
          {page === "recipes" ? <RecipesPage {...props} /> : null}
          {page === "updates" ? <UpdatesPage {...props} /> : null}
          {page === "settings" ? (
            <SettingsPage {...props} demoEnabled={api.demo} onDemoChange={toggleDemo} />
          ) : null}
          </>}
          </>}
        </main>
      </div>
    </div>
  );
}
