# AI Inference Optimization Lab — UI Quality Gates

## Verification matrix

- Resolutions: **1024×768**, **1440×900**, **1920×1080**; both light/dark; Linux is mandatory, and any other platform actually shipped must be checked for native window chrome.
- Scenarios: controller connected/disconnected; worker ready/stale/contaminated; model compatible/incompatible; plan accepted/`PREFLIGHT_REQUIRED`; feasible/infeasible contexts; simulation-only phase; job active/failed/completed (when actually implemented); chart missing data; log stream interrupted; recipe needing approval.
- Theme/geometry: no clipped navigation/window buttons, offscreen dialogs, inappropriate scrollbars, unreadable muted text, distorted charts, inconsistent unit spacing or broken focus outlines.
- Interaction: keyboard nav, disabled action explanation, tab order, inspect/copy links, no false confirmation, no warning hidden by tooltip.

## Performance and scientific correctness

1. Rendering and live plotting must not contaminate benchmark measurements. Use sensible update frequency, data decimation and visible sampling window; evaluate CPU/GPU effects empirically where supported.
2. Never fabricate throughput, confidence, memory or temperature on missing observations. Distinguish projected, estimated, actual, failed and infeasible.
3. Confirm units: tok/s not tokens, ms vs s, GiB vs GB; tokens/context semantics consistent. Show model/engine/device and provenance with each comparison.
4. UI closing must leave any controller-owned running experiment unaffected; test when real workflow phase enables it.
5. `PREFLIGHT_REQUIRED` and stale snapshot cannot enable valid submit via frontend-only bypass.
6. Browser/renderer does not access unauthorized filesystem roots or launch native GPU workloads.
7. Offline by default; no new outbound analytics/fonts or silent update-check telemetry.

## Accessibility

- WCAG AA contrast under rendered conditions; target 4.5:1 text and 3:1 non-text where relevant.
- Accessible charts must have readable tabular alternative and interpretable legend/axis labels.
- Focus visible throughout menus, wizard, tables, inspector and dialogs. Reduced motion respected.
- Status not color-only; explicit labels and time since heartbeat.
- Every form has labels, validation relationships and actionable error guidance.

## Visual regression

Use existing Playwright/e2e where available. For a web-renderer component, `expect(page).toHaveScreenshot()` is appropriate after deterministic test data is injected. For native chrome, also capture actual Electron screen; browser-only screenshots cannot validate OS window buttons. Same OS/browser/font version is required for stable golden baselines.

Example **adaptation only** (replace route/fixtures once verified):

```ts
import { test, expect } from '@playwright/test';

test('experiment planner desktop - dark', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/real-route-from-implementation');
  await expect(page.getByRole('main')).toBeVisible();
  await expect(page).toHaveScreenshot('experiment-planner-dark.png');
});
```

## Nonnegotiable sign-off

- Real application inspected, with screenshots for at least representative screens and meaningful error states (or explicit 'unverified' limitation).
- Current repository lint/typecheck/tests/build pass, or precise known failures are disclosed.
- Explicit distinction of UI implemented vs backend supported vs mock/fixture.
- No incompatible engine comparisons or fake graph 'best' labels.
- No newly introduced benchmark contamination, unauthorized network traffic or violations of controller/worker lifecycle boundary.
- No automatic snapshot acceptance of regressions.

## Evidence format

List each tested view with OS, app version, viewport, theme, data source, screenshot path, observed defects, fixes, and rerun result. Report exact commands rather than generic 'tests passed'.
