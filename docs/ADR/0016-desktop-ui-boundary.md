# ADR 0016 — Desktop UI boundary and secure Electron transport

- Status: Accepted
- Date: 2026-10-21
- Phase: 6

## Context

The PRD requires a Linux-first Electron/React operator console, but Electron
must never own benchmark jobs, engine processes or benchmark evidence. The
controller remains the only authority for planning, scheduling, finalization
and recipe qualification. The renderer also must not receive the operator
bearer token or unrestricted filesystem/network access.

The UI has to work in three situations:

1. packaged Electron with the privileged preload bridge;
2. Electron development mode against a loopback Vite server;
3. an optional browser build served from the controller origin, with no
   desktop bridge.

## Decision

### Process boundary

- `apps/desktop/electron` is the Electron main/preload boundary.
- The React renderer is built by Vite into static assets under
  `apps/desktop/dist`.
- The renderer talks to the controller only through a narrow preload API:
  `appInfo`, settings status/storage, a validated `/api/v1` request proxy,
  event subscribe/unsubscribe and a native report save dialog.
- The main process owns the bearer token, API base URL and report write. The
  renderer never sees the token after it is stored.
- No feature in the desktop UI launches an engine, worker, controller or
  optimizer. Closing/hiding the window only closes UI connections. A system
  tray, when available, can reopen the window or quit the UI; durable jobs
  continue because they are controller-owned.

### Transport

- Packaged mode serves the renderer through a privileged `lab://app` custom
  protocol. The protocol handler resolves only files beneath the bundled
  `dist` directory and rejects traversal, unknown hosts, non-file paths and
  path escapes.
- Production responses carry a strict CSP (`connect-src 'none'`, no inline
  scripts) plus `nosniff`, no-referrer, same-origin and permissions headers.
- Development mode may use only `http://127.0.0.1` or `http://localhost` for
  Vite, with a separate CSP that permits the Vite HMR websocket. The
  production path never uses `file://`.
- The request proxy accepts only `GET`/`POST /api/v1/...`, rejects traversal and
  encoded path escapes, caps request/response sizes, uses `redirect: "error"`,
  and attaches the bearer token only in the main process.
- SSE is proxied by the main process with `Last-Event-ID` and reconnect
  backoff. The renderer receives sequenced events through IPC only.

### Security defaults

- `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`,
  `webSecurity: true`, no webviews, no new windows, navigation blocked except
  the trusted app/dev origin, and permission requests denied.
- Hardware acceleration is disabled before `app.disableHardwareAcceleration`
  can take effect (`app.whenReady()`). `LAB_DESKTOP_ENABLE_GPU=1` is the only
  explicit override and requires a restart; shared-GPU qualification then
  requires contamination verification.
- On Linux, persistent tokens are written only when
  `safeStorage.isEncryptionAvailable()` is true and the selected backend is not
  `basic_text`. Otherwise the token remains in main-process memory for the
  session. No plaintext token file is created.
- Report saves use a native dialog, a basename-only filename, a 4 MiB content
  cap and mode `0600`.

### UI truthfulness

- Demo data is a separate `DemoClient` selected by `?demo=1` or local storage;
  every screen is visibly labelled `OFFLINE DEMO MODE`.
- Finalization labels `SIMULATED`, `NO_VALIDATED_WINNER` and `VALIDATED_WINNER`
  are rendered from the controller response. Simulated evidence is never shown
  as deployable, and a winner is never inferred from highest throughput.
- Comparisons display paired confidence intervals, per-context winners,
  incomplete coverage and explicit ineligibility reasons.
- Release intelligence is not implemented in Phase 6. The Updates screen says
  so and never fetches or installs a release.

## Consequences

- The UI can be rebuilt and unit-tested without a GPU, controller, worker or
  network.
- A real GUI run against a live controller/worker still depends on operator
  approval and durable evidence. Source build, unit tests, an unpacked Linux
  package and the packaged `.deb` are not the same as a real benchmark run.
- The optional browser build reuses the React renderer but has no
  `window.labDesktop`; it uses the configured `VITE_API_BASE_URL` and
  `VITE_OPERATOR_TOKEN` at build time. It is not a privileged desktop client.
- Linux installation, signing/upgrade/rollback and AppImage packaging remain
  release-hardening work (Phase 8), not silent side effects of the UI.
