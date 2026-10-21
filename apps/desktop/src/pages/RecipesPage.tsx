import { useEffect, useMemo, useState } from "react";
import type { RecipeView } from "../lib/contracts";
import { usePolling } from "../lib/hooks";
import {
  formatBytes,
  recipeToBash,
  recipeToSystemd,
  shortId,
  toYaml,
} from "../lib/format";
import {
  Badge,
  EmptyState,
  ErrorNotice,
  KeyValues,
  Notice,
  PageHeader,
  Panel,
  Spinner,
  StatusBadge,
  Tabs,
} from "../components/ui";
import type { PageProps } from "./types";

type RecipeKind = {
  schema_version?: string;
  engine?: { id?: string; version?: string; build?: string; executable?: string; sha256?: string; source_commit?: string };
  model?: { id?: string; artifact_digest?: string; files?: { path?: string; sha256?: string; size_bytes?: number }[] };
  hardware?: { gpu_model?: string; gpu_uuid?: string; min_vram_bytes?: number };
  launch?: { executable?: string; argv?: string[]; env?: Record<string, string>; bind_host?: string };
  constraints?: { require_full_context_proof?: boolean; min_improvement_pct?: number; confidence_level?: number };
  validation?: { validated?: boolean; confidence_ref?: string; metrics_ref?: string };
  notes?: string[];
};

type ExportFormat = "json" | "yaml" | "bash" | "systemd";

function RecipeDetail({ api, view }: { api: PageProps["api"]; view: RecipeView }) {
  const recipe = view.recipe as RecipeKind;
  const [format, setFormat] = useState<ExportFormat>("json");
  const [verification, setVerification] = useState<Record<string, unknown> | null>(null);
  const [promotion, setPromotion] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const content = useMemo(() => {
    if (format === "json") return JSON.stringify(recipe, null, 2);
    if (format === "yaml") return toYaml(recipe);
    if (format === "bash") return recipeToBash(recipe);
    return recipeToSystemd(recipe);
  }, [format, recipe]);

  const extension = format === "bash" ? "sh" : format === "systemd" ? "service" : format;

  const exportRecipe = async () => {
    setBusy("export");
    setError(null);
    try {
      await api.saveReport(`recipe-${view.recipe_id}.${extension}`, content);
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(null);
    }
  };

  const verify = async () => {
    setBusy("verify");
    setError(null);
    try {
      setVerification(await api.verifyRecipe(view.recipe_id));
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(null);
    }
  };

  const promote = async (dryRun: boolean) => {
    const slot = window.prompt("Target promotion slot (never written without explicit confirmation):", "active");
    if (!slot) return;
    if (!dryRun && !window.confirm(`Promote recipe ${view.recipe_id} to slot “${slot}”? This requests a guarded deployment command.`)) {
      return;
    }
    setBusy(dryRun ? "dry-run" : "promote");
    setError(null);
    try {
      setPromotion(await api.promoteRecipe(view.recipe_id, { target_slot: slot, dry_run: dryRun }));
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(null);
    }
  };

  const files = recipe.model?.files ?? [];

  return (
    <div className="grid-2 recipe-detail">
      <div className="stack">
        <Panel
          title={view.recipe_id}
          subtitle={`Digest ${shortId(view.recipe_digest, 32)} · created ${new Date(view.created_at).toLocaleString()}`}
          actions={<Badge tone={view.status === "validated" ? "ok" : "warn"}>{view.status}</Badge>}
        >
          <KeyValues
            items={[
              { label: "Engine", value: `${recipe.engine?.id ?? "unknown"} · ${recipe.engine?.version ?? "?"} · build ${recipe.engine?.build ?? "?"}` },
              { label: "Executable", value: <span className="mono wrap">{recipe.engine?.executable ?? "not recorded"}</span> },
              { label: "Executable SHA-256", value: <span className="mono wrap">{recipe.engine?.sha256 ?? "missing"}</span> },
              { label: "Source commit", value: recipe.engine?.source_commit ?? "not recorded" },
              { label: "Model", value: recipe.model?.id ?? "unknown" },
              { label: "Artifact digest", value: <span className="mono wrap">{recipe.model?.artifact_digest ?? "missing"}</span> },
              { label: "GPU", value: `${recipe.hardware?.gpu_model ?? "unknown"} · ${recipe.hardware?.gpu_uuid ?? "unknown"}` },
              { label: "Minimum VRAM", value: formatBytes(recipe.hardware?.min_vram_bytes) },
              { label: "Bind host", value: recipe.launch?.bind_host ?? "not recorded" },
              { label: "Full-context proof", value: recipe.constraints?.require_full_context_proof ? "required" : "not required" },
              { label: "Improvement gate", value: `${recipe.constraints?.min_improvement_pct ?? 5}%` },
              { label: "Confidence", value: `${Math.round((recipe.constraints?.confidence_level ?? 0.95) * 100)}%` },
              { label: "Experiment", value: view.experiment_id },
              { label: "Candidate", value: view.candidate_id },
              { label: "Confidence reference", value: <span className="mono wrap">{recipe.validation?.confidence_ref ?? "missing"}</span> },
              { label: "Metrics reference", value: <span className="mono wrap">{recipe.validation?.metrics_ref ?? "missing"}</span> },
            ]}
          />
          {recipe.validation?.validated ? (
            <Notice tone="ok" title="Recipe validation recorded">
              Qualification evidence is referenced by path and digest in the recipe record. Verification still re-checks
              installed binaries and artifacts; a recipe is not a license to skip checks.
            </Notice>
          ) : (
            <Notice tone="warn" title="Recipe is not validated">
              No deployment artifact should be derived from this record.
            </Notice>
          )}
          {(recipe.notes?.length ?? 0) > 0 ? (
            <ul className="warning-list">
              {recipe.notes?.map((note) => <li key={note}>{note}</li>)}
            </ul>
          ) : null}
        </Panel>

        <Panel title="Model artifacts">
          {files.length === 0 ? <EmptyState title="No artifact files recorded" /> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Path</th><th>Size</th><th>SHA-256</th></tr></thead>
                <tbody>
                  {files.map((file, index) => (
                    <tr key={`${file.path ?? index}`}>
                      <td className="mono wrap">{file.path ?? "—"}</td>
                      <td>{formatBytes(file.size_bytes)}</td>
                      <td className="mono wrap">{file.sha256 ?? "missing"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      <div className="stack">
        <Panel
          title="Export"
          subtitle="Files are written only through the native save dialog after an explicit action."
          actions={
            <button className="button button-primary" onClick={exportRecipe} disabled={busy !== null}>
              {busy === "export" ? "Saving…" : "Save file"}
            </button>
          }
        >
          <Tabs<ExportFormat>
            tabs={[
              { value: "json", label: "JSON" },
              { value: "yaml", label: "YAML" },
              { value: "bash", label: "Bash" },
              { value: "systemd", label: "systemd" },
            ]}
            value={format}
            onChange={setFormat}
          />
          <pre className="code-block">{content}</pre>
          {error ? <ErrorNotice error={error} /> : null}
        </Panel>

        <Panel title="Verification and promotion" subtitle="Both actions are explicit; neither runs automatically.">
          <div className="button-row">
            <button className="button button-secondary" onClick={verify} disabled={busy !== null || view.status !== "validated"}>
              {busy === "verify" ? "Verifying…" : "Verify installation"}
            </button>
            <button className="button button-secondary" onClick={() => promote(true)} disabled={busy !== null || view.status !== "validated"}>
              {busy === "dry-run" ? "Checking…" : "Promotion dry run"}
            </button>
            <button className="button button-danger" onClick={() => promote(false)} disabled={busy !== null || view.status !== "validated"}>
              {busy === "promote" ? "Requesting…" : "Promote"}
            </button>
          </div>
          <p className="muted">
            Promotion is disabled for non-validated recipes by the controller. Verification checks the installed binary
            and artifact hashes without downloading or replacing anything.
          </p>
          {verification ? (
            <div className="result-box">
              <strong>Verification result</strong>
              <pre>{JSON.stringify(verification, null, 2)}</pre>
            </div>
          ) : null}
          {promotion ? (
            <div className="result-box">
              <strong>Promotion result</strong>
              <pre>{JSON.stringify(promotion, null, 2)}</pre>
            </div>
          ) : null}
        </Panel>

        <Panel title="Launch plan" subtitle="Argv is shown as stored. The UI never rewrites engine flags.">
          <KeyValues
            items={[
              { label: "Executable", value: <span className="mono wrap">{recipe.launch?.executable ?? "missing"}</span> },
              { label: "Environment", value: <span className="mono wrap">{JSON.stringify(recipe.launch?.env ?? {})}</span> },
            ]}
          />
          <pre className="code-block">{JSON.stringify(recipe.launch?.argv ?? [], null, 2)}</pre>
        </Panel>
      </div>
    </div>
  );
}

export function RecipesPage({ api, navigate }: PageProps) {
  const recipes = usePolling(() => api.recipes(), 20_000);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedId && recipes.data?.recipes.length) setSelectedId(recipes.data.recipes[0]!.recipe_id);
  }, [recipes.data, selectedId]);

  const selected = recipes.data?.recipes.find((recipe) => recipe.recipe_id === selectedId);

  return (
    <>
      <PageHeader
        eyebrow="Deployment artifacts"
        title="Recipes"
        description="Validated recipes are reproducible launch plans with hashes and evidence references. Simulated or unqualified evidence cannot reach this list."
        actions={<button className="button button-secondary" onClick={recipes.refresh}>Refresh</button>}
      />
      {recipes.error ? <ErrorNotice error={recipes.error} onRetry={recipes.refresh} /> : null}
      {!recipes.data ? <Spinner label="Loading recipes" /> : null}
      {recipes.data && recipes.data.recipes.length === 0 ? (
        <Panel>
          <EmptyState
            title="No validated recipes"
            detail="A recipe requires real measured evidence, a paired baseline in every required context, a ≥5% improvement with the confidence interval strictly above baseline, and no guardrail failure."
            action={<button className="button button-secondary" onClick={() => navigate("compare")}>Inspect results</button>}
          />
        </Panel>
      ) : null}
      {recipes.data && recipes.data.recipes.length > 0 ? (
        <>
          <div className="recipe-tabs">
            {recipes.data.recipes.map((recipe) => (
              <button
                key={recipe.recipe_id}
                className={`recipe-tab ${recipe.recipe_id === selectedId ? "active" : ""}`}
                onClick={() => setSelectedId(recipe.recipe_id)}
              >
                <span>
                  <strong>{recipe.recipe_id}</strong>
                  <small>{recipe.experiment_id}</small>
                </span>
                <StatusBadge value={recipe.status} />
              </button>
            ))}
          </div>
          {selected ? <RecipeDetail key={selected.recipe_id} api={api} view={selected} /> : <EmptyState title="Select a recipe" />}
        </>
      ) : null}
      <Panel title="Lifecycle" subtitle="Recipe promotion remains an audited operator action.">
        <ol className="timeline-list">
          <li><strong>Finalize</strong><span>Paired samples and guardrails produce a validated winner or no winner.</span></li>
          <li><strong>Create recipe</strong><span>The controller records a content-addressed launch plan and evidence references.</span></li>
          <li><strong>Verify</strong><span>The worker confirms the installed executable and model artifact hashes.</span></li>
          <li><strong>Dry-run promotion</strong><span>The controller checks the target slot without replacing anything.</span></li>
          <li><strong>Promote</strong><span>Explicit operator confirmation is required. Deployment installation is Phase 8 and remains unimplemented.</span></li>
        </ol>
        <p className="muted">
          No recipe is created from a simulated study. The UI displays the controller's status; it cannot override
          qualification.
        </p>
      </Panel>
    </>
  );
}
