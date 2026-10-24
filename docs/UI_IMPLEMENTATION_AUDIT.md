# Workstation UI implementation — 2026-10-24

## Verified phase and scope

The canonical PRD is `docs/prd.md` v2.1 (lowercase filename on Linux).
Phase 0–7 plus Phase 8 offline hardening is implemented. Later status entries
record actual installed 0.5.0 measurements for both engines and a saved Strata
recipe; these supersede early statements that no real trial has run. The working
desktop is 0.6.0, with serving acceptance still blocked by external GPU activity.
Clean-host, L40S, full-context and production deployment gates remain open.
This change creates no new benchmark evidence or recipe.

The checkout already contained extensive backend, desktop, contracts and archive
changes. Those were preserved. No generated contract, PRD, engine/model artifact,
service installation or existing database was edited for this initiative.

## Audit and implementation decisions

React 19 / TypeScript 6 / Vite 8 / Electron 41 use plain CSS; no Tailwind,
shadcn, TanStack Table or chart dependency is installed. Existing semantic
components and bounded SVG charts are sufficient for this slice; no dependency
migration or remote font was introduced. Hash routes expose the ten specified
screens plus the existing Help route. API aliases derive from generated contracts;
all Electron controller calls retain validated IPC. Native BrowserWindow frame,
sandbox, CSP and hardware-acceleration policy remain unchanged.

Initial code audit found oversized headings, 248px navigation, rounded cards,
gradient branding, blurred header, generous spacing and limited trial inspection.
No pre-change screenshot was captured; screenshots document the resulting UI.

Implemented `src/workstation.css` as an explicit final semantic layer, preserving
existing component rules and user changes. Neutral layered surfaces, 216px sidebar,
21px headings, 32px controls, compact tables, restrained blue accents and tabular
numerals apply across supported screens. The proposed palette was reconciled with
existing token names. System, dark and light appearance persist locally. Added
workspace skip link, global keyboard focus and reduced-motion rules.

Live Runs is the representative implemented real-workflow screen. A keyboard
operable trial button selects an immutable candidate and observation inspector:
identity, role, context, measurement status, PP/TG tok/s, TTFT ms, peak memory and
parameters. Missing values use the existing unavailable formatter. No confidence
or qualification is inferred. At <=1200px the inspector stacks, and technical
tables scroll within their panel. Existing six-step planner, stale readiness,
idempotent submission, comparison confidence and recipe gates are preserved.
Demo connectivity now says Fixture data rather than Controller online.

Screenshot review found a long plan digest wrapping in a compact status tile;
it now uses a single-line monospace ellipsis. Full identity remains in Run details.
The demo target-worker badge also stretched across its row; its flex sizing was
corrected. Existing truthful simulation notices remain prominent.

## Evidence

Run `npm --prefix apps/desktop run build`, then
`node scripts/capture_workstation_ui.mjs` from the repository root.
The script launches the actual Electron app on Linux with a disposable unmanaged
profile, sandbox enabled and no engines/services started. It uses explicit offline
demo fixtures, captures all eleven routes at 1024×768, 1440×900 and 1920×1080
in dark/light, plus preflight, inspector and disconnected-controller views.
`docs/evidence/ui-workstation/inventory.json` records viewport captures and verifies
no document overflow and no renderer `require`. Captures are evidence, not golden
baselines; no automatic acceptance of changed images is used. Dates in fixtures
are fixed, but relative timestamps naturally depend on capture date.

`node scripts/capture_workstation_native.mjs` captures actual Linux desktop chrome
in both themes through Electron's screen capture, cropped to this application's
bounds. Other desktop content is excluded. Native images are display-scaled;
viewport screenshots separately verify exact requested pixel dimensions. These
scripts use temporary debugging connections only in the isolated invocation.

Reviewed examples include both Live Runs themes, 1024px planner, 1920px analytical
Compare, native frame and selected-trial inspector. No title-bar replacement or
platform-specific simulated window buttons were added.

## Remaining limitations

- Visual data is explicitly labelled fixture data. A disconnected controller is
  a connectivity error, never evidence that a durable run failed.
- Stale-preflight blocking/recovery is covered by existing tests; no connected
  stale worker was induced for native screenshot acceptance.
- No GPU contamination/performance study, large-trial virtualization benchmark,
  clean-host/package installation or full live real-run acceptance was performed.
- No all-control screen-reader/contrast audit or Windows/macOS chrome acceptance
  is claimed. Primary text and muted text use the handoff's AA-oriented palette;
  secondary existing chart/status colors still need exhaustive rendered auditing.
- The inspector is responsive but not manually resizable. Existing SVG chart
  functionality is retained; no new chart or telemetry data source was invented.
- Earlier operator-authorized desktop supervision stops owned local services on
  Quit, unlike the PRD's independent-system-service lifecycle. This pre-existing
  architectural deviation is not resolved by a UI task. Native lifecycle smoke
  checks mocked prompt choices, not survival of real running jobs on Quit.
- Production packaging was not rebuilt or installed. These screenshots validate
  the current source-built Electron application, not the installed package.

## Files changed by this initiative

- `apps/desktop/src/App.tsx`, `App.test.tsx`: appearance, skip navigation,
  fixture connectivity and regression coverage.
- `apps/desktop/src/main.tsx`, `workstation.css`: shared semantic theme/density layer.
- `apps/desktop/src/pages/LiveRunsPage.tsx`, `LiveRunsPage.test.tsx`: selected
  candidate inspector and disconnected-history semantics/tests.
- `scripts/capture_workstation_ui.mjs`, `scripts/capture_workstation_native.mjs`:
  isolated actual-Electron evidence capture.
- This audit, `docs/IMPLEMENTATION_STATUS.md`, and `docs/evidence/ui-workstation/`.

Final visual inventory: 66 route/viewport images, six preflight/inspector images,
one disconnected image and two native-frame images (75 PNGs). Native capture
needed a first-frame warmup and explicit window placement on the captured display;
wrong-monitor diagnostic images were rejected and removed. An initial harness
attempt used unsupported Electron CDP Browser window methods; viewport emulation
and the main-process native capture replaced that attempt. A failed Pillow X11
root capture was not counted as evidence. Only reviewed app images are retained.

## Completion follow-up — 2026-10-24 (supersedes the initial slice limitations)

The current status checklist is `docs/UI_COMPLETION_CHECKLIST.md`. The original
75-image inventory above is historical; the completion evidence is kept separately
under `docs/evidence/ui-workstation-completion/`.

Implemented paged/sortable scientific tables (`DataRows.tsx`, 50 mounted records
per table), bounded plot marks and table alternatives, trial search, adjustable and
collapsible inspector, model search, explicit comparison provenance/context filter,
accessible export tabs, inert dialog background/focus restoration, semantic status
precedence and honest pending/disconnected histories. Failure notices are capped
with all codes still available through paged observations and selected inspection.
The six-step planner exposes the queued preflight command, validates budgets,
keeps advanced limits collapsed, and refuses creation in demo mode at UI/API layers.

During final review, the operator requested icon-only utilities and then revised
placement: the final design uses **one compact light/dark toggle next to refresh
in the header**. Earlier sidebar theme controls were removed. System appearance
can be restored in Settings. Lucide React 1.61.0 is pinned in package.json and the
npm lockfile, supports the installed React 19 peer range, is bundled locally and
adds no runtime network access. Shell/navigation icons share an 18px, 1.75 stroke
system. Refresh is now a single page-data action, dispatched to mounted read-only
queries, including selected worker snapshots, recipes and release detail. Removed
redundant panel/page refresh controls. Explicit readiness, verification, upstream
checks and engine actions are never triggered by page refresh.

Also corrected cache isolation: switching from demo to a disconnected controller
cannot retain fixture observations without a demo label. Hooks tag response state
with the API source and remount page-local state on lane change. Same-source
refresh errors retain the last verified run with a timestamp and disable mutations.

The mypy failure was reproduced first. Removing its stale ignore exposed missing
inference for the dynamic command union; annotating the adapter explicitly as
`TypeAdapter[CommandResult]` passes both normal and nonincremental mypy. Runtime
parsing, durable schema and generated contracts are unchanged.

### Evidence interpretation

`verify_workstation_ui.mjs` launches the real sandboxed Linux Electron application
with isolated unmanaged profiles and explicit fixture scenarios. It checks exact
viewport dimensions, theme application, document overflow, rendered text contrast,
preflight blocking and 5,000-record bounds. The initial QA harness incorrectly
used hash-only navigation for theme changes; final captures force reload and assert
the applied theme. Rejected runs are not counted as light-mode acceptance.

`qa-report.json` holds renderer TaskDuration/ScriptDuration deltas over a two-second
idle window after collection, JS heap and attached DOM counts. These describe this
fixture run only. They do not measure inference throughput, GPU contamination or
worst-case initial rendering latency. SVG plots remain static between controller
updates. All retained records remain available in paged tables/export.

`verify_workstation_keyboard.mjs` uses actual Chromium key input for theme toggling,
modal focus/trapping/Escape and recipe tabs. Its first attempts omitted required
CDP Enter/focus details and failed; the final script supplies focus emulation and
virtual-key/text data. Component tests separately cover busy-Escape refusal and
cache/record bounds. A jsdom focus-order issue prompted explicit DOM-order sorting
of focusable dialog elements; browser keyboard behavior was then verified.

### Lifecycle authorization and boundaries

Recorded operator requests for desktop-managed runtime are in IMPLEMENTATION_STATUS
section 10; subsequent explicit close/Quit behavior is documented in ADR 0019 and
status sections 13–14. The code still has `requestQuit` call `runtime.stop()` for a
managed runtime; unmanaged mode quits UI connections only. Help already documents
Minimize versus Quit. Overview, sidebar, review and Live Runs copy now reflect
those actual modes rather than promising that all Quit paths preserve local jobs.
No service topology or shutdown behavior was changed. PRD AC-01/AC-02 independent
service acceptance remains open and cannot be established by mocked prompt choices.

### Remaining gates

No new real benchmark, hardware acceptance, package install or production mutation
was performed. Full screen-reader/non-text contrast coverage, platform matrix,
clean-host and independent-system-service acceptance remain open. `npm audit`
reports four existing advisories (Electron and undici high; Vitest and mocker
moderate); no broad framework upgrade was made during UI work. These are release
follow-ups, not passed security gates. No external fonts or telemetry were added.

### Final observed result

Final screenshots: 84 PNGs (66 route/theme/size, 14 explicit scenario views,
2 large-trial details, 2 native frame views). The final checks found no document
horizontal overflow and zero text-contrast failures in measured states. Two-second
idle renderer task deltas after CDP garbage collection were 45.1 ms dark and
40.5 ms light, with 201 plotted marks, 153 paged comparison rows and about 10–11 MB
JS heaps. This does not measure total process RSS or certify GPU cleanliness.
Seven actual Electron keyboard checks, 101 desktop tests, 141 Python tests,
typecheck/build/Ruff/mypy/contracts and diff checks passed. Exact command results
are recorded in the final IMPLEMENTATION_STATUS entry.

Files additionally changed in the follow-up: `components/DataRows.tsx`, `Icons.tsx`,
`Charts.tsx`, `Workstation.test.tsx`; `lib/hooks.ts`, `hooks.test.tsx`, `api.ts`,
`mock.ts`, `mock-scenarios.test.ts`; all supported page components (shared table,
query-state, refresh or interaction refinements), `test/setup.ts`, npm manifest/
lockfile, and the explicit adapter annotation in API `services/commands.py`.
New verification helpers: `scripts/verify_workstation_ui.mjs`,
`workstation-contrast.mjs`, `verify_workstation_keyboard.mjs`. Existing native
capture now writes to the completion evidence folder. Earlier failed harness and
jsdom-only attempts are documented above and are not represented as passes.
