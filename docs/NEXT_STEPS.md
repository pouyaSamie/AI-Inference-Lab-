# Next steps

Last updated: 2026-10-21.

## Current state

Phases 0/1/2/3/4/5/6 are committed locally. Phase 6 adds the secure
Electron/React operator console and a locally built Debian package. It is
verified offline/unit/typecheck/build/package only. No full GUI run against a
live controller and worker has been performed.

No real preflight or trial has been run, no model has been fully hashed, and no
validated real recipe exists. Simulated and demo evidence remain
non-promotable.

Read `docs/progress/PHASE_2_REPORT.md` through
`docs/progress/PHASE_6_REPORT.md` for evidence and
`docs/IMPLEMENTATION_STATUS.md` for the complete status table.

## Completed — Phase 6

- Added `apps/desktop`: an Electron 40 + React 19 + TypeScript + Vite operator
  console outside the pnpm workspace.
- Implemented all ten primary screens: Overview, Models, Engines, Workers,
  Optimize, Live Runs, Compare, Recipes, Updates and Settings.
- Added generated-contract aliases, a typed API client, SSE parsing/reconnect,
  polling hooks, SVG charts, report export and explicit offline fixtures.
- Optimize uses the existing snapshot-only plan endpoint and six-step immutable
  plan submission; it does not perform a live worker call during planning.
- Compare renders paired confidence intervals, per-context winners, incomplete
  coverage and `VALIDATED_WINNER` / `NO_VALIDATED_WINNER` / `SIMULATED`
  without inferring a winner from throughput.
- Added secure Electron main/preload boundaries: `lab://app` plus strict CSP,
  sandbox/context isolation, blocked navigation/permissions/webviews, denied
  direct renderer network access, validated `/api/v1` IPC proxy, SSE bridge and
  native bounded report save.
- The renderer never receives the bearer token. Tokens are stored via
  safeStorage only when an encrypted, non-`basic_text` backend is available;
  otherwise they remain in main-process memory for the session.
- Hardware acceleration is disabled before ready. `LAB_DESKTOP_ENABLE_GPU=1` is
  the explicit restart-requiring override, with contamination verification
  required for shared-GPU qualification.
- Added offline demo mode. Every demo screen is labelled and cannot create,
  cancel or qualify real evidence.
- Added a read-only worker snapshot endpoint for cached inventory views, with
  API-flow coverage and regenerated contracts.
- Added Vitest coverage for all screens, finalization labels, IPC validation,
  report bounds, SSE parsing and API proxy authentication/size/error behavior.
- Added `scripts/package-linux.mjs`, which builds an 84.0 MiB `.deb` from the
  local Electron distribution using `dpkg-deb` without network access.
- Added ADR 0016 documenting the UI/Electron security boundary.

Verification run:

```bash
uv run ruff check
uv run ruff format --check
uv run mypy python
uv run pytest -q
uv run python scripts/check_contracts.py
pnpm typecheck
npm --prefix apps/desktop test
npm --prefix apps/desktop run build
npm --prefix apps/desktop run package:linux
systemd-analyze verify packaging/systemd/lab-*.service
```

The `.deb` was inspected and its packaged Electron binary was smoke-launched
with `--no-sandbox`; normal sandboxed launch from the cached development
Electron install failed because its `chrome-sandbox` helper is user-owned mode
`755`. The archive records root:root mode `4755`, but the package was not
installed. AppImage packaging and signing are deferred.

## Immediate work — Phase 7

Phase 7 is release intelligence. It must remain read-only/opt-in and must never
mutate an installed engine, model or the current recipe.

- Add a persisted update-notice model and capability-diff format.
- Support importing release metadata from an offline fixture or an explicitly
  enabled outbound source. No engine artifact download and no execution.
- Compare the reported release surface with the observed installed build:
  version/build/commit, flags, model compatibility, context limits and
  unsupported/renamed commands.
- Classify impact as compatible, requires targeted rerun, incompatible or
  unknown. Missing evidence is `unknown`, never compatible by default.
- Produce a paired old/new benchmark plan for operator approval, without
  replacing the current engine. A rejected update must leave current engine
  fingerprints, recipes and evidence untouched.
- Persist pin/defer/qualify decisions and audit events.
- Wire release notices into the Updates screen as read-only information. The UI
  must not auto-update Electron or engines.
- Add offline tests for capability diffs, impact classification, approval gates,
  non-mutation and rollback/rejection state.

## Pending operator approvals

These actions need explicit approval and are not started:

1. A full SHA-256 scan of `/home/pouya/ai-lab/models` (~270 GiB first run).
2. One real llama.cpp preflight on the RTX 3060.
3. One paired baseline plus low-impact real candidate trial (4K context, short
   repetition) on an idle GPU.
4. A full GUI run against a live controller/worker, and a packaged `.deb`
   installation/upgrade test.
5. Any intensive multi-context benchmark campaign.
6. Installing or enabling any systemd unit.
7. Any download, engine replacement or model mutation (normally forbidden).
8. AppImage tooling acquisition, signing or release publication.

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

- Do not promote simulated, demo, `screening_only`, character-fallback or
  hash-incomplete evidence.
- Do not let the Electron renderer receive the operator token, launch engines or
  own durable jobs.
- Do not enable hardware acceleration silently or treat a UI build as evidence.
- Do not run Optuna inside FastAPI or share controller/optimizer databases.
- Do not add subprocess/network/filesystem/hardware access to adapters.
- Do not terminate unowned processes or write under model/engine roots.
- Do not hand-edit generated contracts.
