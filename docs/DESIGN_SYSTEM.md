# AI Inference Optimization Lab — Design System

Status: **proposed UI design contract** subordinate to the repository PRD v2.1, architecture, security and verified implementation status.

## 1. Product character

Build a **precision engineering workstation** for diagnosing, benchmarking and optimizing local inference. The interface should convey engineering rigor: explicit units, exact provenance, clear constraints, reproducible experiments and honest uncertainty. Primary reference: OpenAI Codex desktop's quiet utility; secondary: Linear's information density; tertiary: Apple-like visual restraint. Not an Apple clone; not a toy AI dashboard.

Design priorities:
1. **Correct technical decisions:** legible performance comparisons, provenance and confidence.
2. **Low visual noise:** content-first workbench; narrow, restrained accents, no neon GPUs/glass/gradients.
3. **Immediate state awareness:** worker/controller connectivity, leases and experiments' true status.
4. **Deep inspection without navigation thrash:** split panes, density, drawers/inspectors, keyboard shortcuts.
5. **Local-first privacy:** never require remote fonts, analytics, model downloads or outbound UI dependencies.
6. **Accessibility and cross-platform behavior:** desktop keyboard UX and real Linux/Windows constraints.

## 2. Visual grammar

- Theme: **dark-first** with complete high-quality light mode. Dark ≠ black; use layered neutral surfaces and quiet separators.
- Accent: muted cool blue. Semantic red/amber/green are for measured and operational states only; plots may use multiple distinguishable colors for data series.
- Fonts: `Inter` or installed system sans; `ui-monospace`/compatible for context counts, tokens/s, paths, commit hashes, commands. Never depend on external font downloads at runtime.
- Size scale: caption 12px/16, normal UI 13px/18, body 14px/20, section 16px/24, title 21px/28. Technical metrics can be larger for true analytical salience, not decoration.
- 4px spacing base; component control height 32–36px; table row 34–38px default. Radius 4/6/10px small/regular/large. Modest 1px borders and surface distinction instead of heavy shadows.
- Tabular numerals for live metrics; right-aligned numeric table columns; **always show unit** (`tok/s`, `ms`, `GiB`, `%`, `°C`, `J`, if actually available), context length (tokens) and confidence/aggregation basis.
- Text hierarchy: metadata subdued but readable; avoid ultra-low contrast for important worker/engine state.

## 3. Semantic tokens

`styles/design-tokens.css` provides an initial theme with the shadcn family of `--background`, `--foreground`, `--card`, `--primary`, `--muted`, `--border`, `--ring`, `--sidebar` and product-specific status/density variables. Verify with existing style infrastructure; do **not** import unchanged into a fully tokenized app.

- Foreground/background contrast >=4.5:1 for ordinary text, and >=3:1 for meaningful UI visual boundaries where required.
- Status is represented in words/icons/position **as well as** color: queued; preflight required; ready; running; paused; cancelling; cancelled; failed; completed; infeasible; stale/unknown. Use backend vocabulary, don't normalize away distinct states.
- Accessibility: persistent focus, correct headings and tab order, tooltip on icon-only buttons, reduced-motion, keyboard navigation.
- Color palettes for multiple chart series must pass distinguishability checks; never rely only on hue.

## 4. Layout and density

**Recommended workspace shell**: left sidebar navigation (about 208–240px), slim header identifying controller/worker context, main table/chart workspace, and optional right contextual inspector (approximately 320–380px). Panels are resizable/collapsible where suitable.

**Page types:**
- *Catalog*: Models, Engines, Workers, Recipes — filterable dense table + detail inspector.
- *Guided task*: Optimize — six-step wizard, explicit preflight, immutable review, no hidden estimates.
- *Operational*: Live Runs — event timeline, trial grid, chart stack, streaming logs, worker state.
- *Analytical*: Compare — synchronized multi-context charts, confidence, units, direct provenance and export.
- *Administrative*: Settings — connection/proxy/no-egress, approved paths, retention and permissions.

Optimize for 1440×900 and 1920×1080; functional minimum 1024×768. Avoid content width caps that waste desktop workspace. When narrow, collapse inspector before squeezing charts into nonsense. Horizontal scrolling is acceptable **inside** wide technical tables, never across the whole document.

## 5. Chart and measurement rules

- Distinguish measured, calculated, modeled, estimated and unavailable. Never plot an estimated number with the same semantics as a measured benchmark.
- Every plotted metric must identify x/y variables, units, engine/build, model revision, context, device and scoring method when needed for interpretation.
- Include confidence intervals or visible 'insufficient evidence' indication when statistical contract requires it; do not fabricate certainty.
- Proper handling for time series gaps, missing telemetry, infeasible 128K, OOM, incomparable Strata/llama.cpp inputs, and different hardware.
- Default plots: tokens/s vs context length; TTFT; prefill/decode performance; memory headroom; Pareto frontier. Choose renderer and downsampling based on verified performance; never assume a graphics engine eliminates GPU contamination.
- Offer accessible tables for plotted data. Keep chart color palette stable across views; legends never disappear behind panels.

## 6. Components

Build a small reusable library from existing infrastructure. Evaluate shadcn/ui for consistent accessible primitives when appropriate; TanStack Table for headless grids/virtualization when needed; ECharts only if the charts truly require it and renderer/GPU trade-offs are tested. No wholesale framework migration.

Must standardize: app shell, sidebar, command bar, data table, table toolbar, status badge, connected/stale banner, multi-step wizard, grouped form, capability selector, context matrix, search-depth selector, preflight result, immutable summary, run-stage timeline, trial grid, chart frame, units formatter, log viewer, result details inspector, recipe diff/export, error and empty states, dialogs, progressive disclosure.

## 7. Native Electron correctness

- Do not assume CSS can implement genuine macOS Liquid Glass. Prefer native frame and system controls unless validated custom title bar requirement exists.
- Respect Window Controls Overlay safe areas and `app-region: drag/no-drag` on platforms that support custom chrome; buttons in draggable areas must remain interactive.
- **Electron renderer is a client of the FastAPI controller**. It never launches/owns native engines or long-running trials; quitting Electron cannot cancel jobs. A worker is a separately managed privileged/system lifecycle concern.
- Local files and paths are worker/backend-owned, not arbitrary browser/Electron renderer access. UI shows approved/persisted data only.
- Minimize renderer-heavy telemetry; measure GPU/CPU pollution before optimizing chart transitions.

## 8. Definition of visual completion

Actual screenshot review (not code inspection alone); responsive and keyboard QA; local-first/no external network inspection; no fake live data; chart labels/provenance complete; consistent light/dark themes; no impact to running jobs and service architecture.
