# Next steps

Last updated: 2026-10-21.

## Current state

Phases 0/1/2/3/4/5 are committed locally. Phase 5 (statistical finalization and
recipe qualification) is implemented and verified offline. No real preflight or
trial has been run, no model has been fully hashed, and no validated real recipe
exists.

Read `docs/progress/PHASE_2_REPORT.md`, `docs/progress/PHASE_3_REPORT.md`,
`docs/progress/PHASE_4_REPORT.md` and `docs/progress/PHASE_5_REPORT.md` for the
evidence and `docs/IMPLEMENTATION_STATUS.md` for the complete status table.

## Completed — Phase 5

- Added `CandidateRole.BASELINE` and a fixed-default baseline ask per selected
  context before TPE candidates.
- Added `BenchSample` retention for every completed primary-level repeat.
- Candidate optimizer values are objective ratios against the paired baseline,
  not raw throughput at different context sizes.
- Added `lab_core.finalization`: per-context objective ratios, deterministic
  paired percentile bootstrap, the >=5% / 95% qualification gate, complete
  coverage cross-context aggregation and explicit `VALIDATED_WINNER` /
  `NO_VALIDATED_WINNER` / `SIMULATED` classifications.
- `/api/v1/experiments/{id}/results` now exposes finalization evaluations and
  `validated_winner_candidate_id`.
- `POST /api/v1/recipes` recomputes qualification and refuses simulated,
  screening-only, incomplete, unpaired or non-qualified evidence with `409`;
  accepted recipes are stored as `validated`.
- Simulated observations now retain labelled repeat samples but remain
  non-promotable end to end.
- Full gate passed: `48 passed`, 110 files formatted, mypy clean in 92 source
  files, contracts current and `pnpm typecheck` passed.

## Immediate work — Phase 6

Phase 6 is the local operator UI. It must not add a second backend contract or
weaken the existing execution/finalization boundaries.

- Add the local Electron/React/Vite shell using generated TypeScript contracts.
- Show worker/inventory freshness, experiment lifecycle, feasibility, search
  progress, per-context finalization, paired confidence and recipe status.
- Keep simulation labels prominent; never present a `SIMULATED` or
  `NO_VALIDATED_WINNER` result as deployable.
- Add UI tests that use the generated contract types and offline fixtures.
- Keep the UI read/operate path on the existing bearer-authenticated API.

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
3. One paired baseline plus low-impact real candidate trial (4K context, short
   repetition) on an idle GPU.
4. Any intensive multi-context benchmark campaign.
5. Installing or enabling any systemd unit.
6. Any download, engine replacement or model mutation (normally forbidden).

## Real validation entry evidence

Before any real recipe is claimed, collect:

- complete engine and source-shard hashes, including every Strata source shard;
- a real preflight result with effective context and resource outcome;
- one eligible measured baseline and candidate at the same context and workload,
  with at least two retained primary samples each;
- TTFT, decode throughput, telemetry, quality/stability evidence and a passing
  near-capacity context check;
- the qualification decision and any failed contexts for an honest
  `NO_VALIDATED_WINNER` result;
- a second GPU run if hardware becomes available.

## Do not

- Do not promote simulated, `screening_only`, character-fallback or
  hash-incomplete evidence.
- Do not run Optuna inside FastAPI or share controller/optimizer databases.
- Do not add subprocess/network/filesystem/hardware access to adapters.
- Do not terminate unowned processes or write under model/engine roots.
- Do not hand-edit generated contracts.
