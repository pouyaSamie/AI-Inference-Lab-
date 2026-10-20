# Next steps

Last updated: 2026-10-21.

## Current state

Phase 0/1/2 are committed. Phase 3 (adapter productionization and conformance)
is implemented, verified and committed locally. No real preflight or trial has
been run, no model has been fully hashed, and no validated real recipe exists.

Read `docs/progress/PHASE_2_REPORT.md` and `docs/progress/PHASE_3_REPORT.md` for
the evidence and `docs/IMPLEMENTATION_STATUS.md` for the complete status table.

## Completed — Phase 3

- llama.cpp server and `llama-bench` help are parsed and checked separately;
  required flags are verified for each binary before the manifest is accepted.
- Capability extraction considers only option-definition lines, not prose.
- Candidate values are validated strictly by observed descriptor kind.
- Strata `0.1.44.1` uses integer `--expert-cache`, `--pool-workers=0` for all
  cores, explicit `--kv-resident` bounds, and observed profile flags only.
- Strata profile generation strips adapter-managed base args, never stringifies
  the `native: true` discovery marker, and emits `--native SHARD1` only from an
  explicit `native_shard`.
- Offline golden fixtures and conformance tests cover plans, evidence parsing,
  profile de-duplication and generated-file digests.
- Full gate passed: `33 passed`, 106 files formatted, mypy clean in 90 source
  files, contracts current and `pnpm typecheck` passed.

## Immediate work — Phase 4

Phase 4 adds real benchmark corpora, real serving/full-context evidence and the
statistical groundwork without weakening the simulation boundary.

- Resolve the Strata source shard path during read-only model discovery and
  record it as `native_shard`; keep the pack usable without the flag when it is
  unresolved.
- Add deterministic tokenizer-backed 4K/32K workloads and the full-context
  serving harness.
- Exercise one operator-approved real llama.cpp preflight and one low-impact
  trial on an idle GPU, then record the actual results.
- Keep Strata full-context `INCONCLUSIVE` until the serving harness proves it.
- Do not promote `screening_only`, simulated or hash-incomplete evidence.

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

## Phase 4 entry evidence

Before Phase 4 claims validation, collect:

- complete engine and model hashes;
- a real preflight result with effective context and resource outcome;
- at least one real serving trial with TTFT, decode throughput, telemetry and
  quality/stability evidence;
- an explicit OOM/failure ledger for infeasible contexts;
- a second GPU run if hardware becomes available.

## Do not

- Do not promote simulated, `screening_only` or hash-incomplete evidence.
- Do not run Optuna inside FastAPI or share controller/optimizer databases.
- Do not add subprocess/network/filesystem/hardware access to adapters.
- Do not terminate unowned processes or write under model/engine roots.
- Do not hand-edit generated contracts.
