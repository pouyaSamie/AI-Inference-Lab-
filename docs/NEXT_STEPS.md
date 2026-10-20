# Next steps

Last updated: 2026-10-21.

## Current state

Phase 0/1 are committed. Phase 2 (real Linux worker) is implemented and its
static gate plus live protocol/discovery smoke passed. No real preflight or
trial has been run, and no model has been fully hashed. No validated real recipe
exists.

Read `docs/progress/PHASE_2_REPORT.md` for the evidence and
`docs/IMPLEMENTATION_STATUS.md` for the complete status table.

## Immediate work — Phase 3

Phase 3 productionizes the two supported adapters against the installed builds
and adds conformance coverage. It must not add a third engine.

### 3.1 llama.cpp adapter

- Keep every argument conditional on the observed `--help` flags.
- Cover server, native microbench and OpenAI-compatible serving plans with
  installed-build fixtures.
- Test unsupported flags (`UNSUPPORTED_FLAG`), context limits, shard paths,
  quoting and response parsing.
- Ensure command plans carry observed executable and model digests.

### 3.2 Strata adapter

- Encode only behavior supported by the installed `0.1.44.1` candidate.
- Treat version/help output on stderr correctly.
- Do not invent `models list`, `models inspect`, `doctor`,
  `engine calibrate` or `bench run`; use the installed CLI and pack/profile
  JSON.
- Keep full-context proof explicitly `INCONCLUSIVE` until Phase 4.
- Add parser/plan fixtures for the installed profile shape.

### 3.3 Conformance and contract work

- Add sanitized fixtures for every newly observed flag or error shape.
- Test that a changed engine digest fails closed before spawning.
- Test generated-file and profile digests.
- Regenerate contracts only from Pydantic/FastAPI and run the drift gate.
- Update `docs/ARCHITECTURE.md`, implementation status and add a Phase 3 report.

### 3.4 Verification gate

```bash
uv run ruff check
uv run ruff format --check
uv run mypy python
uv run pytest -q
uv run python scripts/check_contracts.py
pnpm typecheck
systemd-analyze verify packaging/systemd/lab-*.service
```

Do not mark Phase 3 complete until all applicable commands have actually run.

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
