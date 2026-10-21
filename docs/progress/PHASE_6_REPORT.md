# Phase 6 report — secure Electron operator UI and local Linux packaging

Date: 2026-10-21

Status: **implemented, verified offline and packaged locally. This report is
part of the Phase 6 local commit. Not accepted as a live GUI run.** No
controller/worker session was started for the UI, and no benchmark, preflight or
recipe was produced by this phase.

This report records only work actually performed. A rendered fixture, a unit
test, a production build or a `.deb` is not benchmark evidence.

## 1. Delivered

### Desktop application shell

- Added `apps/desktop`, an Electron 40 + React 19 + TypeScript 6 + Vite 8
  application outside the pnpm workspace.
- The renderer implements all ten primary screens:
  **Overview, Models, Engines, Workers, Optimize, Live Runs, Compare, Recipes,
  Updates and Settings**.
- Added a typed controller client using generated contract aliases in
  `src/lib/contracts.ts`. No second hand-written payload contract was added.
- Added polling hooks, SSE parsing with replay floors, reconnect/backoff and
  stale-sequence reset, deterministic formatting, SVG charts and report export.
- Added explicit offline demo fixtures selected by `?demo=1` or Settings. Every
  screen displays `OFFLINE DEMO MODE`; demo actions cannot create or qualify
  real evidence.
- Added a system tray when the desktop supports one. Closing the window hides
  it to the tray; **Show operator console** reopens it and **Quit UI** exits.
  Controller-owned jobs are unaffected. Minimal desktops without a tray fall
  back to normal close/exit.

### Screens and truthfulness

- **Overview** shows controller/optimizer health, worker/GPU summary, active
  studies, recent experiments and recipes.
- **Models** lists cached worker inventory, files/shard counts, hash completeness,
  compatibility and Strata source-shard context.
- **Engines** shows registered engine identity, build/commit, executable hash,
  command capabilities and model compatibility.
- **Workers** shows hardware, GPU UUID/VRAM, engines/models, active leases,
  warnings, snapshot age and heartbeat state.
- **Optimize** implements the six-step flow: target worker/GPU/model/engine,
  objective, contexts, search budget, preflight result and submission. It calls
  the existing snapshot-only planning endpoint and submits the immutable plan;
  it does not probe a worker from the UI.
- **Live Runs** shows experiment lifecycle, feasibility, trial progress,
  telemetry/charts, events and pause/resume/cancel controls. It tolerates SSE
  gaps by resetting to a snapshot.
- **Compare** displays finalization, paired intervals, per-context winners,
  cross-context coverage, ineligibility reasons and the Pareto/trend views.
  `SIMULATED` is rendered as **never a deployable winner**; highest throughput
  alone is never presented as a pass.
- **Recipes** displays stored recipes, digests, qualification status and the
  explicit `409` rejection path; it does not promote or install anything.
- **Updates** is a truthful Phase 7 boundary: it does not check, download,
  replace or install an engine/model.
- **Settings** configures the controller URL and operator token, shows secure
  storage status, demo mode, security defaults and the GPU-acceleration
  override warning.

### Secure Electron boundary

- Added a main/preload split. The renderer is sandboxed with
  `contextIsolation: true`, `nodeIntegration: false`, `webSecurity: true`, no
  webviews, denied permissions and blocked foreign navigation/new windows.
- Packaged assets are served through the privileged `lab://app` protocol with a
  strict CSP (`default-src 'none'`, `connect-src 'none'`, `frame-ancestors
  'none'`) and traversal/unknown-host rejection.
- Development uses only a loopback Vite origin (`127.0.0.1` or `localhost`) with
  a separate CSP. `file://` is not a production path.
- Added a validated main-process API proxy: only `GET`/`POST /api/v1/...`,
  traversal/encoded-traversal rejection, 1 MiB request cap, 8 MiB response cap,
  `redirect: "error"`, no-store caching and a 30 s timeout. The bearer token is
  attached only in the main process.
- Added a main-process SSE bridge with `Last-Event-ID`, backoff, bounded
  buffering and sender-scoped unsubscribe. The renderer never opens an API or
  SSE connection directly.
- Added safeStorage-only persistence: a token is written only when the OS
  backend is encrypted and not `basic_text`; otherwise it stays in
  main-process memory for the session. No plaintext token file is written.
- Added a native report save dialog with a basename-only name, extension
  allowlist, 4 MiB content cap and mode `0600`.
- Hardware acceleration is disabled before `whenReady()`.
  `LAB_DESKTOP_ENABLE_GPU=1` is the explicit restart-requiring override; the
  Settings screen records that shared-GPU qualification then requires
  contamination verification.
- Packaged builds disable DevTools; development keeps them enabled.

### Cached inventory endpoint

The Models/Workers screens require cached inventory. Added:

```text
GET /api/v1/workers/{worker_id}/snapshot
```

It requires the operator token, returns the latest stored `WorkerSnapshot`,
and returns `404` for a missing worker or missing snapshot. It never contacts
the worker. API-flow tests cover success/missing, and OpenAPI/JSON
Schema/manifest/TypeScript contracts were regenerated.

### Packaging

- Added `scripts/package-linux.mjs`. It builds the renderer/Electron entrypoints,
  copies the installed Electron distribution, installs the compiled app under
  `resources/app`, writes a Debian control file, launcher, desktop entry and
  icon, and invokes `dpkg-deb --root-owner-group`.
- It performs no network access and does not install the package.
- The resulting package records `chrome-sandbox` as root:root mode `4755`.
- Added `build/icon.svg` and `public/tray.png`; the tray icon is copied into the
  production bundle by Vite.

## 2. Verification actually performed

Final Python gate:

```bash
uv run ruff check
# All checks passed!

uv run ruff format --check
# 110 files already formatted

uv run mypy python
# Success: no issues found in 92 source files

uv run pytest -q
# 49 passed in 9.16s

uv run python scripts/check_contracts.py
# contracts are current
```

Desktop gate:

```bash
npm --prefix apps/desktop test
# 8 test files, 27 tests passed

npm --prefix apps/desktop run typecheck
# renderer, Electron main/preload and test-type tsc pass

npm --prefix apps/desktop run build
# Vite production renderer + Electron build pass
# dist/assets/index-D6mtp7Yi.js 311.51 kB (gzip 90.95 kB)
# dist/assets/index-DRtlQKTH.css 22.81 kB (gzip 5.15 kB)
```

Root typecheck also passes:

```bash
pnpm typecheck
# @lab/client-contracts tsc pass
# desktop renderer/Electron tsc pass
```

Packaging:

```bash
npm --prefix apps/desktop run package:linux
# built ai-inference-lab-desktop_0.1.0_amd64.deb
# 88,110,330 bytes (84.0 MiB)
# sha256 1d8635d5e99eba1c39fad2c36870d2ddc15b0929154117500fb3f1ecfb804832
```

`dpkg-deb --info`/`--contents` confirmed:

- package name/version `ai-inference-lab-desktop 0.1.0`, architecture `amd64`;
- control/postinst, launcher, desktop entry and scalable icon;
- packaged Electron binary and `resources/app/package.json`;
- `chrome-sandbox` archived as `-rwsr-xr-x root/root`.

The `.deb` was extracted to `/tmp/opencode/lab-deb-extract` and the packaged
Electron binary was smoke-launched with `--no-sandbox` for 10 s. It stayed
running until killed by the test timeout and produced no preload, CSP or
`Failed to start` console errors. Extraction as a normal user gives the
`chrome-sandbox` file user ownership; only an actual root installation preserves
the archived root:root setuid helper.

The freshly built development binary was also smoke-launched with
`--no-sandbox` after adding the tray. It stayed running for the 10 s test window
with no console/tray errors. A prior smoke test left an Electron process alive;
it was verified as this repository's test process and terminated before the
next run. No unowned process was touched.

`systemd-analyze verify packaging/systemd/lab-*.service` parsed all three units;
the only diagnostics were the expected missing deployment executables
`/opt/ai-inference-lab/.venv/bin/lab-*`. No unit was installed or enabled.

## 3. Tests added

- `src/App.test.tsx` renders the shell and every navigation label against demo
  fixtures, asserts the offline label, and opens Compare and Updates.
- `src/pages/ComparePage.test.tsx` covers a measured no-winner result and a
  simulated non-deployable result.
- `electron/security.test.ts` covers API URL/path/method/idempotency/frame/
  report validation, including traversal, encoded traversal, foreign origins,
  scheme/port mismatch and report bounds.
- `electron/api-proxy.test.ts` covers bearer injection only in the main-process
  request, path rejection before fetch, method/body limits, controller error
  propagation, missing token and transport failure.
- `electron/sse-parser.test.ts` and `src/lib/sse.test.ts` cover sequencing,
  replay and gap behavior.
- `src/lib/api.test.ts` verifies that disabling `?demo=1` clears the launch
  override instead of immediately re-entering demo mode.
- `src/lib/format.test.ts` covers deterministic operator formatting.

All tests run without Electron, a display, GPU, live engine, controller or
external network.

## 4. Not performed

- No full GUI session against a live controller/worker and no real experiment
  created through the UI.
- No normal sandboxed launch from the cached Electron development install. Its
  `chrome-sandbox` helper is user-owned mode `755`; changing ownership/mode
  requires privileged action, which was not requested.
- No `.deb` installation, sandboxed launch as installed, signing, upgrade,
  rollback or uninstallation test.
- No AppImage build. `appimagetool` is not installed and downloading it was not
  authorized.
- No tray behavior on every desktop environment; only a local smoke check.
- No native notification, browser-served companion, Playwright end-to-end or
  headless/minimal-WM acceptance run.
- No download of Electron, npm packages or engine/model updates.
- No real preflight, trial, hash scan, recipe or benchmark campaign.
- No systemd installation or enablement.

## 5. Known limitations

- The desktop dependency graph has no committed lockfile. The current
  `node_modules` is environment-specific/symlinked and a clean registry install
  was not performed offline. Reproducible dependency locking remains open.
- `pnpm typecheck` now includes the desktop typecheck, so it requires desktop
  dependencies to be installed even though they are outside the pnpm workspace.
- The `.deb` is a locally authored package, not an electron-builder release.
  Its dependency list and desktop integration have not been install-tested on a
  clean Ubuntu host. AppImage and signing are Phase 8.
- Normal sandboxed launch is unverified on this host because the development
  Electron helper permissions are wrong. The package archive itself records the
  intended mode.
- Data-grid virtualization, TanStack Query/React Router/ECharts, native
  notifications and a browser companion from the PRD's optional stack are not
  implemented; typed hooks, hash navigation, SVG charts and the Electron-only
  transport are used instead.
- Cached inventory does not expose live GPU utilization/temperature; those are
  observation telemetry, not fields of `WorkerSnapshot`. The UI does not invent
  them.
- The UI always trusts controller state. It does not independently recompute
  finalization or promote a candidate; that is deliberate.
- Demo fixtures are deterministic and visibly labelled. They are not evidence
  and cannot create an experiment through the API.
- No real validated recipe exists. Full GUI acceptance (AC-01) and live
  application shutdown during a running trial remain to be exercised with
  operator approval.
