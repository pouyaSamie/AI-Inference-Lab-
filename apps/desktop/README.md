# Desktop operator console

Local Electron + React + TypeScript + Vite UI for the AI Inference Optimization
Lab. It is an operator view/control surface only: the FastAPI controller owns
planning, jobs, evidence, finalization and recipe qualification.

## Prerequisites

- Node 22+ and npm.
- The controller/optimizer running separately (default
  `http://127.0.0.1:8787`).
- An operator token configured in Settings.

This app is intentionally outside the pnpm workspace. There is no committed
`package-lock.json` yet; a clean dependency install currently requires network
access and is not reproducible offline.

## Commands

```bash
npm install
npm run dev          # loopback Vite + Electron, devtools enabled
npm test             # Vitest + jsdom, no display or controller required
npm run typecheck    # renderer + Electron main/preload
npm run build        # Vite production bundle + Electron tsc
npm run start        # build, then launch Electron
npm run package:linux
```

`package:linux` writes
`release/ai-inference-lab-desktop_<version>_amd64.deb` using the locally
installed Electron distribution and `dpkg-deb`. It downloads nothing. The
package is built and inspectable; installation, signing, upgrade/rollback and
AppImage packaging remain Phase 8 work and need operator approval.

## Security boundary

- The renderer is sandboxed with `contextIsolation: true`,
  `nodeIntegration: false` and no webviews.
- Packaged assets use `lab://app` with strict CSP. Development uses only a
  loopback Vite origin.
- The renderer never receives the bearer token. API and SSE traffic goes through
  validated main-process IPC; the proxy accepts only `GET`/`POST /api/v1/...`,
  rejects traversal, caps bodies/responses and uses `redirect: "error"`.
- Navigation, new windows, permissions and devtools (packaged) are blocked.
- Tokens are persisted only through safeStorage with an encrypted non-`basic_text`
  backend; otherwise they remain in main-process memory for the session.
- Report saves use a native dialog, a basename-only filename, a 4 MiB cap and
  mode `0600`.
- Closing the window hides it to the system tray when a tray is available. The
  tray can reopen the window or quit the UI; controller-owned jobs continue
  either way. On minimal desktops without a tray, close exits the UI.
- Hardware acceleration is disabled before ready.
  `LAB_DESKTOP_ENABLE_GPU=1` is the explicit restart-requiring override; any
  shared-GPU qualification then needs contamination verification.

## Demo mode

`?demo=1` or the Settings toggle selects offline fixtures. Every screen shows
`OFFLINE DEMO MODE`. Demo data cannot create/cancel real experiments, cannot
produce a validated recipe and is never evidence.

## Not implemented here

- Release/update installation or engine downloads (Updates is read-only).
- A browser-served companion build.
- Native notifications.
- Playwright end-to-end or live-controller acceptance runs.
- Installer signing, AppImage, or upgrade/rollback verification.
