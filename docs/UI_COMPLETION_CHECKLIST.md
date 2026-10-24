# Desktop UI completion checklist — 2026-10-24

This checklist covers the source-built 0.6.0 UI, not production release acceptance.
The PRD remains v2.1. Phase 0–7 plus Phase 8 offline hardening is the verified
implementation scope. Later status entries record real 0.5.0 llama.cpp and Strata
measurements; the current serving candidate still has separate acceptance gates.

| Requirement | Status | Evidence / remaining action |
| --- | --- | --- |
| Preserve architecture, existing changes, contracts and scientific semantics | Implemented; regression checked | No generated contract edits; worker/API/adapter behavior retained. One explicit `TypeAdapter[CommandResult]` annotation fixes the reproduced mypy failure. |
| Shared shell, typography, density and themes on ten routes plus Help | Implemented; visually checked | All eleven routes at three requested sizes in both themes. Native frame remains Linux-owned. |
| Final requested icon placement | Implemented; checked | One compact light/dark switch beside the refresh icon in the header. No sidebar theme group or header dropdown. Locally bundled Lucide icons also replace mixed navigation glyphs. Follow-system preference is in Settings. |
| Duplicate refresh controls | Implemented; regression checked | One header action refreshes mounted cached page queries; duplicate page/panel refreshes removed from Workers, Recipes, Models, Engines, Overview and Updates. Error retry and run-stream resync remain distinct remediation actions. Refresh never scans files, replans or checks upstream releases. |
| Live Runs inspector and scientific tables | Implemented; tested | Collapse/reopen, keyboard-adjustable width, trial search, explicit unavailable/failure states, numeric alignment, 50-record pages and numeric order controls. All records remain reachable. |
| Optimize six-step flow | Implemented; tested | Cached target selection, context pressed states, explicit constraints, collapsed advanced limits, numeric-budget validation, preflight command/reason and blocked submission until ready. Demo creation is disabled in both UI and facade. |
| Stale/disconnected/empty/loading states | Implemented; tested | Last known run state stays visible on refresh failure; mutations are disabled. Unknown optimizer/scheduler state is not labelled offline/stopped. Failed collection requests do not become empty histories. No fixture cache crosses into a real disconnected source. |
| Comparison provenance and accessible charts | Implemented; tested | Engine build/hash, model/tokenizer/worker and dataset identity where recorded; context plot filter; 40-score / 200-observation plot limits with explicit coverage; paged evidence and plot data alternatives. Missing identity/metrics remain unavailable. |
| Keyboard, focus and modal behavior | Implemented; tested in Electron | Single header toggle, dialog Tab/Shift-Tab/Escape/restoration, inert background, roving recipe tabs with Home/End; media-query stub only in jsdom. No screen-reader certification is claimed. |
| Contrast | Corrected; measured for captured states | Computed rendered text foreground/background checks in both themes; active-step text and native selectors corrected. Control boundary tokens strengthened. This is a scoped audit, not exhaustive WCAG certification. |
| Large datasets and renderer overhead | Bounded; measured on fixtures | 5,000-record fixture, 100 mounted Live Runs trial/observation rows, <=200 scatter marks, 250 retained events. Two-second idle renderer task/heap measurements in QA JSON; no GPU/benchmark contamination certification. |
| Real Linux screenshots | Captured and reviewed | `docs/evidence/ui-workstation-completion/`; labelled default, stale-preflight, partial, empty, error, replay-gap, failed/OOM and large scenarios. Source build and native-frame captures; no production data. |
| Tests, typecheck, build, Python lint/types/contracts | Executed | See final command results in IMPLEMENTATION_STATUS.md; all claimed results refer to observed runs. |
| Independent-service lifecycle PRD acceptance | Externally blocked / pre-existing deviation | Current user-authorized desktop-managed mode stops services on Quit. Minimize keeps them alive. A UI task must not change supervision. Independent system-service hardware acceptance requires an approved deployment/run. |
| Clean-host, two-GPU and full-context acceptance | Externally blocked | No package installation, systemd installation, new real benchmark, production restore, signing or publication authorized here. L40S unavailable. |
| Dependency security and release packaging | Remaining release work | npm audit reports existing Electron/undici/Vitest/mocker advisories (2 high, 2 moderate). No Lucide advisory reported. Resolve and requalify dependency upgrades before release; no broad auto-fix applied. |
| Full assistive-technology / platform matrix | Remaining acceptance work | Screen-reader walkthrough, OS-native chooser behavior, Windows/macOS chrome and hardware contamination acceptance are not established by these screenshots. |

The independent source/UI work is complete within this verified scope. Release
and hardware gates above remain open; none is represented as passed.
