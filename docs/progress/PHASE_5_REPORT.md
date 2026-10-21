# Phase 5 report — paired statistical finalization and recipe qualification

Date: 2026-10-21

Status: **implemented, verified offline and committed locally. No real
preflight, paired baseline, candidate trial or benchmark campaign was run.**

This report records only work actually performed. An offline qualification path
is not real performance evidence, and no validated real recipe exists.

## 1. Delivered

### Paired baseline

- Added `CandidateRole` (`baseline`, `candidate`) and
  `CandidateSpec.role`. Candidate identity remains deterministic over the
  engine/model/worker/context/workload/parameters tuple; role is metadata and
  does not fork a duplicate configuration.
- Added `AskPayload.baseline`. The optimizer's `_defaults()` returns the
  adapter's documented default for each active dimension instead of a TPE
  sample. Missing defaults fail explicitly rather than being guessed.
- The controller schedules one baseline per selected context before normal
  candidates. Baseline asks are recorded with `role=baseline`.
- `studies.maximum_trials` now includes one baseline slot per selected context.
  Baselines are fixed controls, not TPE search proposals, so they do not consume
  the distinct-candidate search budget.
- Candidate `tell` values are objective ratios against the paired baseline. The
  baseline itself tells `1.0`. This replaces raw throughput comparison across
  contexts.

### Retained primary samples

- Added frozen `BenchSample` and `BenchmarkObservation.samples`.
- The real worker derives one sample from each completed primary-level serving
  repeat and records the true `repetitions` count. Missing sample metrics are
  skipped rather than invented.
- The simulated lane emits deterministic labelled samples and a true repetition
  count, but remains `measurement_status=simulated` and non-promotable.
- The observation summary metrics remain the operator-facing medians; finalization
  uses the retained paired samples.

### Statistical scoring and finalization

- Added `objective_ratio()` and `paired_ratio_ci()` to `lab_core.scoring`.
  `paired_log_ratio_ci()` now reuses the same deterministic percentile
  bootstrap.
- Added `lab_core.finalization` with:
  - `ContextEvaluation` and `ContextRanking`;
  - `CrossContextRanking`;
  - `FinalizationResult`;
  - `finalize_experiment(...)`.
- Each candidate/context is compared with the eligible baseline observation for
  the same context. The score is the PRD objective formula; confidence is a
  deterministic paired bootstrap over retained samples.
- Qualification uses the declared policy: by default at least 5% improvement and
  a 95% interval strictly above `1.0`, with no guardrail failure.
- Ineligible evidence is explicit: simulated, non-server, non-measured,
  non-completed, missing throughput, missing full-context proof, missing paired
  samples, missing baseline, or quality-gate failure.
- Cross-context aggregation uses the geometric mean of per-context scores over
  exactly the selected contexts. A missing context makes the candidate
  ineligible for a global winner.
- Results classify `VALIDATED_WINNER`, `NO_VALIDATED_WINNER` or `SIMULATED` and
  expose per-context evaluations, intervals, coverage and warnings.

### API and recipe gate

- `/api/v1/experiments/{id}/results` now includes `finalization` and
  `validated_winner_candidate_id`, while retaining the screening
  `best_candidate_id`.
- `POST /api/v1/recipes` recomputes finalization from stored observations.
  It returns `409` for simulated, screening-only, incomplete, baseline,
  unpaired or non-qualified evidence.
- Accepted candidate recipes are stored with `status=validated` and carry a
  qualification reference plus score/interval notes. Approval, verification and
  promotion remain separate.
- Generated OpenAPI, JSON Schema, manifest and TypeScript contracts were
  regenerated; drift check passes.

### Tests

- `tests/test_finalization.py` covers deterministic paired bootstrap,
  objective ratios, a qualified winner, high-variance inconclusive evidence,
  incomplete cross-context coverage and simulated non-qualification.
- `tests/test_optimizer_engine.py` verifies baseline asks use documented
  defaults.
- `tests/test_api_flow.py` verifies the simulated end-to-end run schedules a
  baseline, retains three primary samples and reports `SIMULATED` with no
  validated winner or context winner.
- A second API test converts the simulated rows to synthetic measured
  baseline/candidate evidence with a 1.5x effect and passing context gates. It
  drives the full recipe endpoint and verifies a `validated` recipe with a
  confidence reference. This is synthetic test data, not engine evidence.
- No test requires a GPU, downloaded weights, a live engine or external network
  access.

## 2. Safety boundaries

- Adapters remain pure.
- The optimizer remains a separate process and owns Optuna.
- Simulated evidence is retained for testing but can never qualify a recipe.
- Character-fallback and native-only evidence remain ineligible.
- A baseline with no observation or failed guards makes the comparison
  ineligible; no zero-throughput or invented value is substituted.
- No real engine, GPU, model or systemd unit was started, installed or changed.
- No unowned process was terminated.

## 3. Commands actually run

Full final gate in this tree:

```bash
uv run ruff check
# All checks passed!

uv run ruff format --check
# 110 files already formatted

uv run mypy python
# Success: no issues found in 92 source files

uv run pytest -q
# 49 passed in 10.49s

uv run python scripts/check_contracts.py
# contracts are current

pnpm typecheck
# tsc --noEmit -p tsconfig.json: passed

systemd-analyze verify packaging/systemd/lab-controller.service \
  packaging/systemd/lab-optimizer.service packaging/systemd/lab-worker.service
# Only the expected missing /opt/ai-inference-lab/.venv/bin/lab-* paths.
# No unit was installed, enabled or started.
```

Targeted checks during development also ran:

```bash
uv run pytest -q tests/test_api_flow.py tests/test_optimizer_engine.py \
  tests/test_finalization.py
# 11 passed
```

## 4. Not performed

- No real `PREFLIGHT` or `CLAIM_TRIAL`.
- No real paired baseline or candidate observation.
- No validated real recipe.
- No live exercise of llama.cpp or Strata serving/tokenizer endpoints.
- No full SHA-256 scan of the ~270 GiB model root.
- No 4K/32K/128K latency, VRAM, quality or thermal evidence.
- No second GPU comparison.
- No systemd installation or enablement.
- No download, engine replacement, weight mutation or unowned-process
  termination.

## 5. Known limitations

- The qualification path is proven by synthetic offline observations and the
  explicitly simulated lane, not by measured engine evidence.
- The simulated end-to-end result therefore reports `SIMULATED`, not a winner.
- Baseline scheduling currently asks every selected context. Contexts that
  preflight later proves infeasible still consume their baseline attempt; the
  finalization result records the missing/ineligible comparison rather than
  inventing a winner.
- Cross-context ranking requires full coverage but does not add a separate
  cross-context confidence interval; each member context must itself pass the
  paired qualification gate.
- Staged finalist re-runs beyond the retained primary repeats are not separately
  budgeted yet. The default workload repetition count provides the paired
  samples used here.
- Strata full-context proof remains `INCONCLUSIVE`; the installed build has no
  calibration or native benchmark command to substitute.
