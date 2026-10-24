# Desktop operator console

Local Electron + React + TypeScript + Vite UI for the AI Inference Optimization
Lab. It is an operator view/control surface only: the FastAPI controller owns
planning, jobs, evidence, finalization and recipe qualification.

## Installed desktop

The 0.6.0 candidate includes a pinned CPython 3.13.16 runtime, locked dependencies,
controller, optimizer and real worker. Open the app; no separate API, Python,
Node or terminal setup is required. The private API binds an OS-assigned
loopback port. The setup wizard has three steps: choose model and inference
folders, select discovered engine builds, then review and save. It recursively
finds GGUF models (including split files), Strata packs and nearby engine support
files. Folder choices save automatically; wizard progress survives reopening.
Use **Edit setup** in Settings to add/remove folders or change builds later.
Individual paths remain available under Advanced for unusual installations.

Model browsing works before an engine is configured. Initial discovery reads
metadata immediately, then automatically verifies imported model files with a
progress bar showing bytes and file counts. Completed hashes are saved privately
and reused while file size and modification time remain unchanged. Quitting stops
verification promptly and keeps hashes of completed files. Real planning waits
for verification automatically and reports concrete failures with a retry action.
Discovery never downloads or modifies model files.

## Run a validated recipe

Open **Recipes**, select the saved recipe, then **Run recipe**. The worker
checks the saved build and model bytes, shows file-verification progress,
reserves the GPU and loads its own engine on a loopback port. A one-token
readiness check and the reported context capacity must pass before **ready**.
Failed starts show a reason and an explicit retry. A busy GPU is refused before
large-file verification and checked again before launch. Benchmark guards are
unchanged. A measured baseline without a qualified improvement is not silently
converted into an optimized recipe.

When ready, expand **Chat with this model** or copy the displayed **Local API
endpoint** into an application on the worker computer. Lab chat needs no API
configuration or key. It uses the engine's tokenizer to enforce the saved context
limit, with bounded messages and replies; **New chat** clears the conversation
from the view. Prompts and replies remain in the local durable command store and
are not diagnostic log fields. Chat creates no benchmark/qualification evidence.

**Stop engine** terminates only this session's owned process group. A late Stop
for an older session cannot stop a replacement. Minimize leaves the engine
running; Quit stops it. Serving must stop before benchmarking or changing local
folders/builds. Sessions do not automatically restart after worker/app relaunch;
expired interactive requests require an explicit retry.

Legacy Strata recipe metadata is not a standalone launch script: **Run recipe**
regenerates the verified native profile from the retained candidate. External
deployment replacement, automatic promotion and systemd installation are outside
this managed local workflow. See `docs/PRODUCTION_READINESS.md` for live gates.

The renderer remains isolated: Electron main supervises a Python runtime owner,
which launches each service as a separate process. The controller owns durable
jobs and the two SQLite files remain separate. Neither model weights, engines,
GPU drivers nor Strata's engine-specific Python environment are bundled.

Closing asks Quit, Minimize to tray, or Cancel. Quit stops local services and owned execution safely.
Without a tray, keep the window minimized or choose controlled exit. Logout
survival and systemd are outside this desktop-managed mode.

Data lives in Electron's per-user `userData/local-lab/`: two databases,
configuration, worker journal, artifacts, migration backups and bounded lifecycle
logs. Runtime credentials are generated automatically. The worker pepper uses a
non-`basic_text` OS keyring; session fallback rotates only this profile's local
worker credential while preserving its durable ID. Disabled workers stay disabled.
Uninstall preserves this directory. No existing external database is imported.

## Engine updates

The engine step recommends the newest identifiable complete installed build per
family. Build metadata is distinguished from unverified folder-name hints.
Startup checks official `ggml-org/llama.cpp` and `Niko1221/Strata` GitHub releases
and suggests updates in a popup. Disable startup checks in Engine updates; this
preference persists. Offline/rate-limited checks do not block local startup.
Stable llama.cpp releases may point to a matching binary release; Strata native
engine versions are read from native assets, not its desktop version.

A read-only hardware check runs once per app startup. Recommendations use the
observed GPU, driver, architecture and Vulkan support to select a compatible
published build. The default action is **Install recommended update…**; archive
choices remain under Advanced. Unknown compatibility is reported explicitly.
Restart after changing a driver to refresh this profile. Execution-time safety
checks and telemetry remain independent. Confirm installation in the native dialog. Verified SHA-256 archives are safely extracted by bundled Python
under private `local-lab/managed-engines`, without running installer scripts or
engines. llama.cpp CUDA installs include the matching verified CUDA runtime
archive; Strata installs its matching control/server/Python archive as well.
The new build is discovered for explicit selection; capability and real measured
qualification remain separate. Existing builds remain in place.

Remove build moves an inactive isolated build to Trash after confirmation. Selected
or shared builds, model-containing directories and source/runtime roots are
protected. Unusual layouts cannot be removed through this action. Engine changes
require no active jobs. Quitting cancels an active download/extraction and removes
its staging directory. Controller release imports and qualification stay offline.

## Source development / build prerequisites

Node 22+, npm, uv, pinned uv-managed CPython 3.13.16 and workspace dependencies.
`npm ci` uses the committed desktop lockfile. Source development retains the
separately managed API/token configuration; installed builds always use the
bundled runtime and ignore development URL/server overrides.

## Commands

```bash
npm ci
npm run dev          # loopback Vite + Electron, devtools enabled
npm test             # Vitest + jsdom, no display or controller required
npm run typecheck    # renderer + Electron main/preload
npm run build        # Vite production bundle + Electron tsc
npm run start        # build, then launch Electron
npm run package:linux
```

`package:linux` writes
`release/ai-inference-lab-desktop_<version>_amd64.deb` using the locally
installed Electron distribution and `dpkg-deb`. It uses the installed pinned Electron distribution and offline uv cache. Prepare build dependencies first; the installed application never installs dependencies. The
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
- Closing asks Quit, Minimize to tray, or Cancel. The tray can reopen a minimized
  window. Quit stops the bundled local services safely.
  Without a tray, close offers minimized background operation or controlled exit.
- Hardware acceleration is disabled before ready.
  `LAB_DESKTOP_ENABLE_GPU=1` is the explicit restart-requiring override; any
  shared-GPU qualification then needs contamination verification.

## Demo mode

`?demo=1` or the Settings toggle selects offline fixtures. Every screen shows
`OFFLINE DEMO MODE`. Demo data cannot create/cancel real experiments, cannot
produce a validated recipe and is never evidence.

## Not implemented here

- Desktop application self-updates, model downloads, or driver installation.
- A browser-served companion build.
- Native notifications.
- Full target-host GUI acceptance and real hardware benchmark qualification.
- Installer signing, AppImage, or upgrade/rollback verification.

### 0.6.2 journey maintenance

Overview now gives a Prepare → Optimize → Review path. Engine maintenance shows
one family at a time, observed download bytes and unpacking state, explicit
completion, and a matching discovered build selection action. Offline release
evidence is under an advanced disclosure. Model verification explains incomplete
and stalled scans and links to file inspection and guarded rescanning. Optimize
discloses Strata search coverage and client/engine timing differences. A raster
window icon and matching Linux launcher identity are included.

`node scripts/capture_journey_qa.mjs` from the repository root launches a real,
unmanaged Electron window with explicit UI fixtures. The temporary visual harness
is not a packaged application entry point. No engine installation is performed
by that capture script. See `docs/PERFORMANCE_COMPARISON_2026-10-24.md` for the
read-only manual benchmark investigation and its remaining matched-run gap.
