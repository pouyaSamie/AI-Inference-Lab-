# Phase 4 report — tokenizer-backed workloads and native shard identity

Date: 2026-10-21

Status: **implemented, verified offline and committed locally. No real
preflight, trial or benchmark campaign was run.**

This report records only work actually performed. A tokenizer-backed harness is
not performance evidence until it runs against an installed engine with
approved resources.

## 1. Delivered

### Frozen corpus and prompt fitting

- Added `lab_bench.corpus` with the frozen, non-secret `lab-synthetic-v1`
  corpus unit. Its SHA-256 is
  `11360040d817aae19dbd595c813c56e939758391b5b3593ad30d57fadce64851`.
- Added iterative `fit_prompt_to_tokens`: the corpus is grown or shrunk against
  a caller-supplied tokenizer callback until it is within a stated tolerance.
  Character estimates are never presented as token counts.
- Unknown dataset IDs or mismatched dataset digests raise `CorpusMismatch`.

### Workload suite contract

- `ClaimTrialPayload` optionally carries the controller's `WorkloadSuite`.
  When present, its canonical digest must match `workload_digest`; a mismatch is
  rejected before a worker can run a different workload.
- The controller now includes `spec.workload` in each durable claim.
- Added `plan_workload_suite`, `primary_case` and `near_capacity_case` so the
  controller and worker share the same fraction/output/seed interpretation.
- Generated OpenAPI, JSON Schema, manifest and TypeScript contracts were
  regenerated; the drift gate passes.

### Worker serving harness

- llama.cpp prompt sizing attempts `/apply-template` followed by `/tokenize`.
  If those routes are unavailable, it falls back to content tokenization; if no
  tokenizer endpoint is usable, the prompt is labelled `character-fallback`.
- Strata prompt sizing uses the installed Anthropic-compatible
  `/v1/messages/count_tokens` endpoint, which counts the rendered prompt.
- Every workload level (for example 25%, 60%, 85% and 98% of usable context)
  runs once. The primary comparable level is repeated according to
  `WorkloadSuite.repetitions`; the near-capacity level is a single stress probe.
- Primary metrics use the median of repeated primary-level requests. Different
  prompt loads are never averaged together.
- A failure stops the ladder. A smaller completed level is never reported as
  though full context passed.
- The near-capacity request is checked against server-reported prompt/output
  usage and effective context. Silent truncation, an over-capacity request or a
  prompt that misses its planned token load marks the serving measurement
  invalid and records `CONTEXT_MISMATCH`.
- Character-fallback evidence is `screening_only`; it cannot become a measured
  observation merely because the HTTP request completed.

### Strata source-shard identity

- Read-only discovery resolves `source_shards` from each pack's
  `conversions.json` against the configured model roots.
- Every shard must match an exact basename and byte size. Missing, ambiguous,
  unreadable or changed shards produce a warning and no `--native` argument.
- All resolved source shards are included in `ModelArtifact.files` with
  `shard_index`/`shard_count`; they are hashed when hashing is enabled.
- The adapter emits `--native SHARD1` only when the first resolved source shard
  is present. The `native: true` discovery marker is never stringified.
- No model or engine file is written, replaced or downloaded.

### Tests

- New `tests/test_workload_protocol.py` covers corpus identity, iterative
  fitting, suite planning, both tokenizer endpoint shapes, labelled fallback,
  primary medians, context-overflow/truncation rejection and token-load
  mismatch handling.
- `tests/test_real_worker_units.py` now covers two-shard Strata source
  resolution, exact size verification, hashing, `files` metadata and the
  missing-`conversions.json` refusal path.
- No test requires a GPU, downloaded weights, a live engine or external network access.

## 2. Safety boundaries

- Adapters remain pure; all filesystem, process, network and hardware access
  stays in the worker.
- No real preflight, trial, benchmark or GPU campaign was run.
- The simulated lane remains non-promotable. Character fallback is also
  non-promotable for measured evidence.
- Missing metrics remain missing; no estimate is substituted for a failed
  tokenizer or a failed serving request.
- Strata full-context proof remains `INCONCLUSIVE` until a real approved run.
- No installed binary or weight was modified, and no unowned process was
  terminated.

## 3. Commands actually run

Full final gate in this tree:

```bash
uv run ruff check
# All checks passed!

uv run ruff format --check
# 108 files already formatted

uv run mypy python
# Success: no issues found in 91 source files

uv run pytest -q
# 42 passed in 8.10s

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
uv run pytest -q tests/test_workload_protocol.py tests/test_real_worker_units.py
# 15 passed
```

## 4. Live read-only discovery evidence

A live scan with hashing disabled resolved both installed Strata packs with no
warnings:

```text
Strata-Qwen3.8-Flash-Next-Q2_0-coder-iq1_m
  native_shard .../Strata-Qwen3.8-Flash-Next-Coder/IQ1_M/
    Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf
  source_shards IQ1_M-00001 (29608446496 bytes), IQ1_M-00002 (28800138432 bytes)

Strata-Qwen3.8-Flash-Next-Q2_0-q2_0
  native_shard .../Strata-Qwen3.8-Flash-Next-Q2_0/models/Q2_0/
    Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00001-of-00002.gguf
  source_shards Q2_0-00001 (37623740192 bytes), Q2_0-00002 (28800138432 bytes)
```

Both artifacts remained `verified=false` because hashing was disabled. A
read-only adapter plan check emitted:

```text
--native .../Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf
```

No source shard was opened for writing.

## 5. Not performed

- No real `PREFLIGHT` or `CLAIM_TRIAL`.
- No live exercise of llama.cpp `/apply-template` or `/tokenize`.
- No live Strata `/v1/messages/count_tokens` request.
- No full SHA-256 scan of the ~270 GiB model root.
- No 4K/32K/128K latency, VRAM, quality or thermal evidence.
- No second GPU comparison.
- No systemd installation or enablement.
- No download, engine replacement, weight mutation or unowned-process
  termination.

## 6. Known limitations

- The workload suite is implemented but has not been run against an installed
  serving process. Endpoint availability and actual token-count agreement remain
  unproven until an approved real run.
- `WorkloadSuite.dataset_sha256` is optional in the frozen contract. When it is
  absent, the worker still uses the frozen corpus but cannot prove the dataset
  identity from a digest; callers should populate it.
- Context feasibility preflight still starts a CPU-offload server at the target
  context. It proves allocation, not GPU residency; candidate trials measure GPU
  fit. This phase did not widen preflight into a GPU campaign.
- Strata full-context proof remains `INCONCLUSIVE`; the installed build has no
  calibration or native benchmark command to substitute.
- Full source-shard hashing is expensive and was not run. The ~270 GiB scan
  remains an operator-approved action.

## 7. Exit criteria met

- [x] Deterministic tokenizer-backed workload corpus exists.
- [x] Every workload level is planned from one controller-owned suite.
- [x] Prompt sizes are fitted with the target engine tokenizer when available.
- [x] Character fallback is explicit and screening-only.
- [x] Primary metrics use repeated-level medians without mixing prompt loads.
- [x] Near-capacity truncation and token-load mismatch are rejected.
- [x] Strata source shards are resolved read-only with exact identity checks.
- [x] Resolved shards are represented in model files and hashed when enabled.
- [x] Contracts, lint, typing, tests and TypeScript checks pass offline.
- [x] No real resource campaign was claimed or hidden.
