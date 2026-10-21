import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  ComparisonPlan,
  ContextLength,
  ImpactAssessment,
  ReleaseDetailResponse,
  ReleaseMetadata,
} from "../lib/contracts";
import { CONTEXTS, CONTEXT_LABELS } from "../lib/contracts";
import { usePolling } from "../lib/hooks";
import { humanEnum, relativeTime, shortId } from "../lib/format";
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
} from "../components/ui";
import type { Tone } from "../components/ui";
import type { PageProps } from "./types";

const RELEASE_TEMPLATE = {
  engine_id: "llamacpp",
  version: "<candidate version>",
  build: "<candidate build>",
  backend: "cuda",
  executable_id: "llama-server",
  artifact_sha256: "<64 lowercase hex characters>",
  released_at: "2026-10-21T00:00:00Z",
  source: "offline_import",
  changed_paths: ["ggml/src/ggml-cuda/<changed-file>.cu"],
  changelog: "Paste the release metadata imported from an approved offline source.",
};

function impactTone(impact: string | undefined): Tone {
  if (impact === "P0") return "danger";
  if (impact === "P1") return "warn";
  return "neutral";
}

function comparisonTone(status: string | undefined): Tone {
  if (status === "improved") return "ok";
  if (status === "regressed" || status === "incompatible") return "danger";
  if (status === "inconclusive") return "warn";
  return "info";
}

function decisionTone(decision: string | undefined): Tone {
  if (decision === "pinned") return "ok";
  if (decision === "deferred") return "neutral";
  if (decision === "comparison_requested") return "info";
  return "warn";
}

function assessmentSummary(assessment: ImpactAssessment) {
  return (
    <div className="stack">
      <div className="button-row">
        <Badge tone={impactTone(assessment.impact)}>{assessment.impact}</Badge>
        <Badge tone={assessment.applicable ? "info" : "neutral"}>
          {assessment.applicable ? "applicable" : "not applicable"}
        </Badge>
        {assessment.requires_smoke ? <Badge tone="warn">smoke test required</Badge> : null}
        {assessment.requires_ab ? <Badge tone="warn">A/B required</Badge> : null}
        {!assessment.model_identity_complete ? <Badge tone="danger">model identity incomplete</Badge> : null}
        {!assessment.inventory_fresh ? <Badge tone="danger">stale inventory</Badge> : null}
      </div>
      <KeyValues
        items={[
          { label: "Recommended action", value: humanEnum(assessment.recommended_action) },
          { label: "Assessment", value: shortId(assessment.assessment_id, 28) },
          { label: "Worker", value: assessment.worker_id },
          { label: "Model", value: assessment.model_id ?? "not selected" },
          {
            label: "Model identity complete",
            value: assessment.model_identity_complete ? "yes" : "no — A/B blocked",
          },
          {
            label: "Current executable SHA-256",
            value: <span className="mono wrap">{assessment.current_engine?.executable_sha256 ?? "not observed"}</span>,
          },
          {
            label: "Candidate executable SHA-256",
            value: <span className="mono wrap">{assessment.candidate_engine_sha256 ?? "missing from release metadata"}</span>,
          },
          { label: "Inventory revision", value: String(assessment.inventory_snapshot_revision ?? "unknown") },
          { label: "Policy", value: assessment.policy_version ?? "release-impact-v1" },
        ]}
      />
      {(assessment.reasons?.length ?? 0) > 0 ? (
        <div>
          <strong>Deterministic reasons</strong>
          <ul className="warning-list">
            {assessment.reasons?.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </div>
      ) : null}
      {assessment.candidate_engine_sha256 ? null : (
        <Notice tone="warn" title="No candidate artifact hash">
          An A/B proposal is blocked. Import official metadata containing the candidate executable SHA-256 so the
          comparison can freeze both identities.
        </Notice>
      )}
      {assessment.model_identity_complete ? null : (
        <Notice tone="danger" title="Model identity is incomplete">
          An A/B proposal is blocked until every selected model file has a verified SHA-256. Re-scan and hash the model,
          then import the release again so the assessment binds a complete model identity.
        </Notice>
      )}
    </div>
  );
}

function ComparisonCard({ comparison }: { comparison: ComparisonPlan }) {
  const result = comparison.result;
  return (
    <article className="result-box">
      <div className="button-row">
        <Badge tone={comparisonTone(comparison.status)}>{humanEnum(comparison.status)}</Badge>
        <span className="mono">{shortId(comparison.comparison_id, 26)}</span>
        <Badge tone="neutral">never installs automatically</Badge>
      </div>
      <KeyValues
        items={[
          {
            label: "Baseline",
            value: `${comparison.baseline_engine.engine_id} ${comparison.baseline_engine.version} · build ${comparison.baseline_engine.build}`,
          },
          {
            label: "Candidate",
            value: `${comparison.candidate_engine.engine_id} ${comparison.candidate_engine.version} · build ${comparison.candidate_engine.build}`,
          },
          { label: "Model", value: comparison.model_id },
          {
            label: "Contexts",
            value: (comparison.contexts ?? []).map((context) => CONTEXT_LABELS[context] ?? context).join(", "),
          },
          { label: "Worker", value: comparison.worker_id },
          { label: "Created", value: relativeTime(comparison.created_at) },
          { label: "Evaluated", value: comparison.evaluated_at ? relativeTime(comparison.evaluated_at) : "not yet" },
        ]}
      />
      {result ? (
        <div className="stack">
          <Notice
            tone={result.status === "improved" ? "warn" : result.status === "regressed" ? "danger" : "info"}
            title={
              result.recommendation === "review_candidate"
                ? "Candidate may be reviewed — it is not approved"
                : "Keep the current engine"
            }
          >
            <p>
              Upgrade approval remains <strong>false</strong>. A separate operator action, installation decision and
              fresh verification are still required.
            </p>
          </Notice>
          {(result.contexts?.length ?? 0) > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Context</th>
                    <th>Status</th>
                    <th>Samples</th>
                    <th>Score</th>
                    <th>Improvement</th>
                    <th>Paired interval</th>
                  </tr>
                </thead>
                <tbody>
                  {result.contexts?.map((context) => (
                    <tr key={context.context}>
                      <td>{CONTEXT_LABELS[context.context] ?? context.context}</td>
                      <td><StatusBadge value={context.status} /></td>
                      <td>{context.sample_count ?? "—"}</td>
                      <td>{context.score?.toFixed(4) ?? "—"}</td>
                      <td>{context.improvement_pct == null ? "—" : `${context.improvement_pct.toFixed(2)}%`}</td>
                      <td>
                        {context.interval
                          ? `${context.interval.lower.toFixed(4)} – ${context.interval.upper.toFixed(4)} at ${Math.round(context.interval.confidence_level * 100)}%`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {(result.reasons?.length ?? 0) > 0 ? (
            <div>
              <strong>Result reasons</strong>
              <ul className="warning-list">
                {result.reasons?.map((reason) => <li key={reason}>{reason}</li>)}
              </ul>
            </div>
          ) : null}
        </div>
      ) : (
        <Notice tone="info" title="Awaiting paired measured evidence">
          <p>
            This page does not benchmark or install anything. After a controlled measured A/B run, submit evidence through
            the controller API using the frozen comparison ID and both engine hashes. Simulated evidence is rejected as
            incompatible.
          </p>
        </Notice>
      )}
    </article>
  );
}

export function UpdatesPage({ api, navigate }: PageProps) {
  const releases = usePolling(() => api.releases(), 20_000);
  const workers = usePolling(() => api.workers(), 30_000);
  const [selectedNoticeId, setSelectedNoticeId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReleaseDetailResponse | null>(null);
  const [detailError, setDetailError] = useState<unknown>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailRevision, setDetailRevision] = useState(0);
  const [workerId, setWorkerId] = useState("");
  const [snapshot, setSnapshot] = useState<Awaited<ReturnType<PageProps["api"]["workerSnapshot"]>> | null>(null);
  const [snapshotError, setSnapshotError] = useState<unknown>(null);
  const [modelId, setModelId] = useState("");
  const [releaseJson, setReleaseJson] = useState("");
  const [importError, setImportError] = useState<unknown>(null);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [decisionNote, setDecisionNote] = useState("");
  const [decisionError, setDecisionError] = useState<unknown>(null);
  const [deciding, setDeciding] = useState<string | null>(null);
  const [contexts, setContexts] = useState<ContextLength[]>([4096]);
  const [comparisonError, setComparisonError] = useState<unknown>(null);
  const [creatingComparison, setCreatingComparison] = useState(false);

  useEffect(() => {
    if (!workerId && workers.data?.workers.length) {
      setWorkerId(workers.data.workers[0]!.worker_id);
    }
  }, [workerId, workers.data]);

  useEffect(() => {
    if (!workerId) {
      setSnapshot(null);
      return;
    }
    let stopped = false;
    setSnapshot(null);
    setSnapshotError(null);
    setModelId("");
    void api
      .workerSnapshot(workerId)
      .then((data) => {
        if (stopped) return;
        setSnapshot(data);
        setModelId(data.models?.[0]?.model_id ?? "");
      })
      .catch((error: unknown) => {
        if (!stopped) setSnapshotError(error);
      });
    return () => {
      stopped = true;
    };
  }, [api, workerId]);

  const selectedId = selectedNoticeId ?? releases.data?.notices[0]?.notice_id ?? null;

  const refreshDetail = useCallback(() => {
    setDetailRevision((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let stopped = false;
    setDetailLoading(true);
    setDetailError(null);
    void api
      .release(selectedId)
      .then((data) => {
        if (!stopped) setDetail(data);
      })
      .catch((error: unknown) => {
        if (!stopped) setDetailError(error);
      })
      .finally(() => {
        if (!stopped) setDetailLoading(false);
      });
    return () => {
      stopped = true;
    };
  }, [api, selectedId, detailRevision]);

  useEffect(() => {
    if (detail && detail.notice.notice_id !== selectedId) setDetail(null);
  }, [detail, selectedId]);

  const latestAssessment = detail?.assessments?.[0] ?? null;
  const installedEngine = snapshot?.engines?.[0]?.engine ?? null;
  const selectedModel = snapshot?.models?.find((model) => model.model_id === modelId);

  const template = useMemo(() => JSON.stringify(RELEASE_TEMPLATE, null, 2), []);

  const importRelease = async () => {
    if (!workerId || !releaseJson.trim()) return;
    setImporting(true);
    setImportError(null);
    setImportMessage(null);
    try {
      const parsed = JSON.parse(releaseJson) as ReleaseMetadata;
      const response = await api.checkRelease({
        worker_id: workerId,
        model_id: modelId || null,
        release: parsed,
      });
      setImportMessage(
        response.result === "imported"
          ? "Release metadata imported. No upstream request or download occurred."
          : response.result === "reused"
            ? "Identical release metadata already existed; the durable notice was reused."
            : "This release already matches the installed build; no update is proposed.",
      );
      setSelectedNoticeId(response.notice.notice_id);
      setDetail({
        notice: response.notice,
        assessments: [response.assessment],
        comparisons: [],
      });
      setReleaseJson("");
      releases.refresh();
      refreshDetail();
    } catch (error) {
      setImportError(error);
    } finally {
      setImporting(false);
    }
  };

  const decide = async (action: "pin" | "defer") => {
    if (!selectedId) return;
    setDeciding(action);
    setDecisionError(null);
    try {
      const updated = await api.decideRelease(selectedId, {
        action,
        note: decisionNote.trim() || undefined,
      });
      setDetail(updated);
      setDecisionNote("");
      releases.refresh();
    } catch (error) {
      setDecisionError(error);
    } finally {
      setDeciding(null);
    }
  };

  const toggleContext = (context: ContextLength) => {
    setContexts((current) =>
      current.includes(context)
        ? current.filter((item) => item !== context)
        : [...current, context].sort((left, right) => left - right),
    );
  };

  const createComparison = async () => {
    if (!selectedId || !latestAssessment || contexts.length === 0) return;
    setCreatingComparison(true);
    setComparisonError(null);
    try {
      const comparison = await api.createComparison({
        notice_id: selectedId,
        assessment_id: latestAssessment.assessment_id,
        contexts,
        objective: "balanced",
        min_improvement_pct: 5,
        confidence_level: 0.95,
      });
      setDetail((current) =>
        current
          ? {
              ...current,
              notice: { ...current.notice, decision: "comparison_requested" },
              comparisons: [comparison, ...(current.comparisons ?? [])],
            }
          : current,
      );
      releases.refresh();
    } catch (error) {
      setComparisonError(error);
    } finally {
      setCreatingComparison(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Read-only release intelligence"
        title="Updates"
        description="Import release metadata offline, classify likely impact, pin or defer a notice, and retain paired A/B proposals. This page never queries upstream, downloads a binary, installs an engine, or approves an upgrade."
        actions={
          <button className="button button-secondary" onClick={() => navigate("engines")}>
            Inspect installed engines
          </button>
        }
      />

      <Notice tone="info" title="Offline import only — no upstream egress">
        <p>
          The controller does not call GitHub or any release feed. Paste approved release metadata. Classification uses
          changed paths, capability-schema diffs and cached worker inventory; unknown paths deliberately fail toward
          smoke testing. A positive comparison never installs or approves a candidate.
        </p>
      </Notice>

      <div className="grid-2">
        <Panel
          title="Offline release import"
          subtitle="No artifact is fetched. The candidate SHA-256 must be present before an A/B proposal can freeze it."
        >
          {workers.error ? <ErrorNotice error={workers.error} onRetry={workers.refresh} /> : null}
          {snapshotError ? <ErrorNotice error={snapshotError} /> : null}
          <div className="form-grid">
            <label>
              Worker
              <select value={workerId} onChange={(event) => setWorkerId(event.target.value)}>
                {workers.data?.workers.map((worker) => (
                  <option key={worker.worker_id} value={worker.worker_id}>
                    {worker.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model
              <select value={modelId} onChange={(event) => setModelId(event.target.value)}>
                <option value="">No model selected</option>
                {snapshot?.models?.map((model) => (
                  <option key={model.model_id} value={model.model_id}>
                    {model.display_name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {installedEngine ? (
            <KeyValues
              items={[
                { label: "Installed engine", value: `${installedEngine.engine_id} ${installedEngine.version} · build ${installedEngine.build}` },
                { label: "Installed SHA-256", value: <span className="mono wrap">{installedEngine.executable_sha256}</span> },
                { label: "Selected model digest", value: <span className="mono wrap">{selectedModel?.files?.[0]?.sha256 ?? "hash not verified"}</span> },
              ]}
            />
          ) : (
            <EmptyState title="No installed build observed" detail="A worker snapshot is required before release impact can be assessed." />
          )}
          <label>
            Release metadata JSON
            <textarea
              rows={12}
              value={releaseJson}
              placeholder={template}
              onChange={(event) => setReleaseJson(event.target.value)}
              spellCheck={false}
            />
          </label>
          <div className="button-row">
            <button className="button button-primary" onClick={importRelease} disabled={!workerId || !releaseJson.trim() || importing}>
              {importing ? "Importing…" : "Import offline metadata"}
            </button>
            <button className="button button-secondary" onClick={() => setReleaseJson(template)} disabled={importing}>
              Load template
            </button>
          </div>
          {importError ? <ErrorNotice error={importError} /> : null}
          {importMessage ? <Notice tone="ok" title="Import result"><p>{importMessage}</p></Notice> : null}
          <p className="muted">
            The template contains placeholders. Replace the version, build, artifact SHA-256 and changed paths with
            approved release data. An import with a missing or malformed candidate hash remains non-comparable.
          </p>
        </Panel>

        <Panel title="Observed installed builds" subtitle="Read from registered worker snapshots, not from the network.">
          {!workers.data ? <Spinner label="Loading worker list" /> : null}
          {workers.data?.workers.length === 0 ? (
            <EmptyState title="No workers registered" detail="No installed build can be observed without a worker snapshot." />
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Worker</th><th>Status</th><th>Snapshot</th><th>Last heartbeat</th></tr></thead>
                <tbody>
                  {workers.data?.workers.map((worker) => (
                    <tr key={worker.worker_id}>
                      <td><strong>{worker.name}</strong><small>{shortId(worker.worker_id, 20)}</small></td>
                      <td>{worker.status}</td>
                      <td>{worker.snapshot_revision > 0 ? `revision ${worker.snapshot_revision}` : "no snapshot"}</td>
                      <td>{relativeTime(worker.last_heartbeat_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <ul className="warning-list">
            <li>Never download, replace, or patch an engine or model from the operator UI.</li>
            <li>Never install a binary silently or as a side effect of opening a screen.</li>
            <li>A newer build invalidates previous hash evidence until it is re-verified and re-benchmarked.</li>
          </ul>
        </Panel>
      </div>

      <Panel
        title="Release notices"
        subtitle="Durable imported metadata and operator decisions. The controller never invents a release feed."
        actions={<button className="button button-secondary" onClick={releases.refresh}>Refresh</button>}
      >
        {releases.error ? <ErrorNotice error={releases.error} onRetry={releases.refresh} /> : null}
        {!releases.data ? <Spinner label="Loading release notices" /> : null}
        {releases.data && releases.data.notices.length === 0 ? (
          <EmptyState
            title="No release notices imported"
            detail="Import approved offline metadata above. This is expected when no release review has been requested."
          />
        ) : null}
        {(releases.data?.notices.length ?? 0) > 0 ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Engine</th><th>Version</th><th>Build</th><th>Source</th><th>Decision</th><th>Imported</th><th /></tr></thead>
              <tbody>
                {releases.data?.notices.map((notice) => (
                  <tr key={notice.notice_id} className={notice.notice_id === selectedId ? "selected" : ""}>
                    <td>{notice.release.engine_id}</td>
                    <td>{notice.release.version}</td>
                    <td>{notice.release.build}</td>
                    <td>{humanEnum(notice.release.source)}</td>
                    <td><Badge tone={decisionTone(notice.decision)}>{humanEnum(notice.decision)}</Badge></td>
                    <td>{relativeTime(notice.imported_at)}</td>
                    <td>
                      <button className="button button-secondary" onClick={() => setSelectedNoticeId(notice.notice_id)}>
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Panel>

      {detailLoading && !detail ? <Panel title="Release detail"><Spinner label="Loading assessment" /></Panel> : null}
      {detailError ? <ErrorNotice error={detailError} onRetry={refreshDetail} /> : null}

      {detail ? (
        <div className="grid-2">
          <div className="stack">
            <Panel
              title={`${detail.notice.release.engine_id} ${detail.notice.release.version} · build ${detail.notice.release.build}`}
              subtitle={`Notice ${shortId(detail.notice.notice_id, 26)} · imported ${relativeTime(detail.notice.imported_at)}`}
              actions={<Badge tone={decisionTone(detail.notice.decision)}>{humanEnum(detail.notice.decision)}</Badge>}
            >
              <KeyValues
                items={[
                  { label: "Source", value: humanEnum(detail.notice.release.source) },
                  { label: "Source commit", value: detail.notice.release.source_commit ?? "not recorded" },
                  { label: "Artifact SHA-256", value: <span className="mono wrap">{detail.notice.release.artifact_sha256 ?? "missing"}</span> },
                  { label: "Changed paths", value: (detail.notice.release.changed_paths ?? []).join(", ") || "not provided" },
                  { label: "Changed areas", value: (latestAssessment?.changed_areas ?? []).join(", ") || "none classified" },
                  { label: "Metadata digest", value: <span className="mono wrap">{detail.notice.metadata_digest}</span> },
                ]}
              />
              {detail.notice.release.changelog ? <p>{detail.notice.release.changelog}</p> : null}
              {latestAssessment ? assessmentSummary(latestAssessment) : <EmptyState title="No impact assessment stored" />}

              <div className="stack">
                <label>
                  Decision note
                  <textarea
                    rows={3}
                    value={decisionNote}
                    placeholder="Why is this release pinned, deferred, or held for comparison?"
                    onChange={(event) => setDecisionNote(event.target.value)}
                  />
                </label>
                <div className="button-row">
                  <button className="button button-secondary" onClick={() => decide("pin")} disabled={deciding !== null}>
                    {deciding === "pin" ? "Pinning…" : "Pin current build"}
                  </button>
                  <button className="button button-secondary" onClick={() => decide("defer")} disabled={deciding !== null}>
                    {deciding === "defer" ? "Deferring…" : "Defer notice"}
                  </button>
                </div>
                {decisionError ? <ErrorNotice error={decisionError} /> : null}
                {detail.notice.decision_note ? <p className="muted">Recorded note: {detail.notice.decision_note}</p> : null}
              </div>
            </Panel>

            <Panel title="Fixed-default A/B proposal" subtitle="Freezes baseline and candidate identities, model digest, worker, workload and contexts.">
              {!latestAssessment ? (
                <EmptyState title="No assessment" detail="An impact assessment is required before a comparison can be created." />
              ) : !latestAssessment.requires_ab ? (
                <Notice tone="info" title="No A/B study required">
                  <p>This release is classified {latestAssessment.impact} with no required comparison. It cannot be promoted from this screen.</p>
                </Notice>
              ) : (
                <>
                  <p className="muted">
                    Every selected context must retain paired samples. Missing contexts or metrics make the comparison
                    ineligible; there is no silent pass.
                  </p>
                  <div className="button-row">
                    {CONTEXTS.map((context) => (
                      <label key={context} className="checkbox">
                        <input
                          type="checkbox"
                          checked={contexts.includes(context)}
                          onChange={() => toggleContext(context)}
                        />
                        {CONTEXT_LABELS[context] ?? context}
                      </label>
                    ))}
                  </div>
                  <div className="button-row">
                    <button
                      className="button button-primary"
                      onClick={createComparison}
                      disabled={
                        creatingComparison ||
                        contexts.length === 0 ||
                        !latestAssessment.candidate_engine_sha256 ||
                        !latestAssessment.model_identity_complete
                      }
                    >
                      {creatingComparison ? "Creating proposal…" : "Create A/B proposal"}
                    </button>
                  </div>
                  {!latestAssessment.candidate_engine_sha256 ? (
                    <p className="muted">Blocked: the release metadata has no candidate executable SHA-256.</p>
                  ) : null}
                  {!latestAssessment.model_identity_complete ? (
                    <p className="muted">Blocked: the selected model does not have a complete verified identity digest.</p>
                  ) : null}
                  {comparisonError ? <ErrorNotice error={comparisonError} /> : null}
                </>
              )}
            </Panel>
          </div>

          <div className="stack">
            <Panel title="Comparisons" subtitle="A/B evidence is retained per proposal. No result changes the installed binary.">
              {(detail.comparisons?.length ?? 0) === 0 ? (
                <EmptyState
                  title="No comparison proposals"
                  detail="Create a proposal to freeze the paired study. Evidence submission remains a separate measured operation."
                />
              ) : (
                detail.comparisons?.map((comparison) => (
                  <ComparisonCard key={comparison.comparison_id} comparison={comparison} />
                ))
              )}
            </Panel>

            <Panel title="Safe update rules" subtitle="These boundaries are deliberate and enforced outside the UI.">
              <ul className="warning-list">
                <li>Import metadata offline; never fetch an artifact from this screen.</li>
                <li>P0/P1 applicable releases require smoke and paired A/B evidence.</li>
                <li>Unknown changed paths fail toward smoke testing rather than being ignored.</li>
                <li>A significant regression or guardrail failure retains the current engine.</li>
                <li>Simulated or non-measured evidence is incompatible and cannot qualify a candidate.</li>
                <li>Upgrade approval is never automatic; installation remains a separate operator decision.</li>
              </ul>
            </Panel>
          </div>
        </div>
      ) : null}
    </>
  );
}
