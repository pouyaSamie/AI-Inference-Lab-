# Next steps

Last updated: 2026-10-21.

## Current state

Phases 0/1/2/3/4 are committed locally. Phase 4 (tokenizer-backed workloads and
Strata source-shard identity) is implemented and verified offline. No real
preflight or trial has been run, no model has been fully hashed, and no validated
real recipe exists.

Read `docs/progress/PHASE_2_REPORT.md`, `docs/progress/PHASE_3_REPORT.md` and
`docs/progress/PHASE_4_REPORT.md` for the evidence and
`docs/IMPLEMENTATION_STATUS.md` for the complete status table.

## Completed — Phase 4

- Added the frozen `lab-synthetic-v1` corpus and iterative tokenizer fitting.
- `ClaimTrialPayload` carries the controller-owned `WorkloadSuite`; a mismatched
  digest is rejected.
- llama.cpp prompt sizing uses `/apply-template` + `/tokenize` when available;
  Strata uses `/v1/messages/count_tokens`.
- Every workload level runs once, the primary level is repeated and medianed,
  and the near-capacity level is a separate stress probe.
- Truncation, overflow and prompt-token mismatch invalidate the serving
  measurement with `CONTEXT_MISMATCH`.
- Character-estimated prompts are explicitly `screening_only`.
- Strata `conversions.json` source shards are resolved read-only with exact
  basename/size checks; all shards are recorded in model files and hashed when
  enabled; `--native SHARD1` is emitted only from a verified path.
- Full gate passed: `42 passed`, 108 files formatted, mypy clean in 91 source
  files, contracts current and `pnpm typecheck` passed.

## Immediate work — Phase 5

Phase 5 turns measured evidence into statistical finalization and recipe
qualification without weakening the simulation or screening boundaries.

- Run the one operator-approved real llama.cpp preflight and low-impact trial,
  then record the actual tokenizer, context, latency and telemetry results.
- Add statistical finalization over repeated samples, including explicit
  confidence/uncertainty handling for the objective.
- Produce recipes only from complete, measured, hash-verified real evidence.
- Keep Strata full-context `INCONCLUSIVE` until a real serving run proves it.
- Do not promote `screening_only`, simulated, character-fallback or
  hash-incomplete evidence.

Verification gate for every phase:

```bash
uv run ruff check
uv run ruff format --check
uv run mypy python
uv run pytest -q
uv run python scripts/check_contracts.py
pnpm typecheck
systemd-analyze verify packaging/systemd/lab-*.service
```

Do not mark a phase complete until all applicable commands have actually run.

## Pending operator approvals

These actions need explicit approval and are not started:

1. A full SHA-256 scan of `/home/pouya/ai-lab/models` (~270 GiB first run).
2. One real llama.cpp preflight on the RTX 3060.
3. One low-impact real trial (4K context, short repetition) on an idle GPU.
4. Any intensive multi-context benchmark campaign.
5. Installing or enabling any systemd unit.
6. Any download, engine replacement or model mutation (normally forbidden).

## Phase 5 entry evidence

Before Phase 5 claims validation, collect:

- complete engine and source-shard hashes, including every Strata source shard;
- a real preflight result with effective context and resource outcome;
- at least one real tokenized serving trial with TTFT, decode throughput,
  telemetry, quality/stability evidence and a passing near-capacity context
  check;
- an explicit OOM/failure ledger for infeasible contexts;
- a second GPU run if hardware becomes available.

## Do not

- Do not promote simulated, `screening_only` or hash-incomplete evidence.
- Do not run Optuna inside FastAPI or share controller/optimizer databases.
- Do not add subprocess/network/filesystem/hardware access to adapters.
- Do not terminate unowned processes or write under model/engine roots.
- Do not hand-edit generated contracts.
