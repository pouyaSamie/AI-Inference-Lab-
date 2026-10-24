# Desktop 0.5.0 installed acceptance — 2026-10-22

## Current acceptance — installed journey completed on this host

This section supersedes the historical status below. Final candidate package:
`apps/desktop/release/ai-inference-lab-desktop_0.5.0_amd64.deb`, SHA-256
`2ff529e6d54d8fbb7ec80b6d16a8bc5c25834e706c56fd2243b3a9da6d4dc8bf`.
The final package is installed over the earlier 0.5.0 follow-up. All 6,852
regular installed files byte-matched the extracted approved package; symlinks
matched. Both real studies below ran through the installed Electron UI in the
normal saved-work profile, with existing read-only engines/models and safeguards.
No model/engine/driver update or download was performed.

| Real 4K study | Baseline prompt/decode tok/s | Candidate prompt/decode tok/s | Retained samples | Result |
| --- | --- | --- | --- | --- |
| llama.cpp / Gemma 12B Q4_0, exp_395444e0… | 1281.6 / 37.1 | 1263.1 / 37.0 | 3 / 3 | Completed; no validated winner |
| Strata / coder IQ1_M, exp_aec8c368… | 91.1 / 37.7 | 97.1 / 10.2 | 3 / 3 | Completed; no validated winner |

Strata's final repeated requests and near-context request logged **0 reused
prompt tokens**. Worker-owned model unload/load occurs before timing each request.
Reported cached tokens now invalidate a measurement rather than inflate prefill
throughput. Previous isolated Strata studies exp_d822ab7e… and exp_87395d19… are
retained diagnostic evidence and must not be used as accepted performance results.
The installed Strata candidate objective ratio was 0.5706 (-42.94%), confidence
interval 0.501–0.715: no candidate qualified and no recipe was created. Earlier
cache-corrected isolated studies exp_ffc875c8… and exp_8985f400… also completed
with measured evidence and are separately backed up; they were not merged into
the normal profile.

Memory safety: the earlier isolated pinned expert arena caused an observed OOM
kill. Final plans use file-backed experts, direct table I/O, no resident arena,
a bounded GPU expert cache and an available-RAM launch guard. Large file RSS is
reclaimable; observed host available RAM stayed around 21–24 GiB during safe runs.
This is not a hard process memory limit. Existing shipped expert profiles are
bounded, read-only, included in model identity and rechecked before launch.

Other verified fixes: native benchmark rows without redundant labels are parsed
from unambiguous token counts; explicit answer-generation policy for each engine;
stream usage requested; llama prompt reuse disabled; quantized V cache requires
explicit flash attention; unavailable completed studies get an explanatory notice;
finished trial state follows observations; evidence tables remain readable.

Actual UI cancellation reached Cancelled and stopped the owned engine. Ten
stat-verified models and saved studies persisted through candidate relaunches.
The operator confirmed the native model-folder picker is usable and reported
cancellation. Diagnostics show the request returned selected, so the exact Cancel
path is operator-reported rather than independently corroborated.
Final native Close choices were operator-assisted and independently recorded
from the real showMessageBox promises: Minimize=1, Cancel=2, Quit=0. Window
hide/show and quit events corroborate the sequence. No response was mocked.
Quit stopped all 11 recorded owned child processes and the main process; both
database files had no open users before final backup.
Installed final relaunch retained ten verified models, selected builds, original
folders and all original studies, including the original cancelled study.
After native Quit, relaunch retained both new completed studies and all ten
verified models. The installed app is left open on the saved Strata comparison.
Expanded startup review showed two hardware badges; modal client and scroll
widths were both 883 px, and Escape dismissed it.

Saved installed study IDs:
- `exp_395444e0-bdb4-5abd-8f1e-d4474e52b2b1` (Gemma/llama.cpp).
- `exp_aec8c368-47b5-5122-b02d-19de790634fc` (Strata coder IQ1_M).

Latest checks: 124 Python tests; 78 desktop tests; mypy; TypeScript; Ruff/format;
contract drift; git diff --check. Bundled private Python ran 48 worker, adapter and
workload regressions. Extracted final package matched all 102 Python source files
and all renderer/Electron assets. Screenshots are under
`apps/desktop/release/acceptance-0.5.0/`: final measured results, comparison, real
cancellation and unavailable-metric explanation.

Verified pre-upgrade backup:
`apps/desktop/release/upgrade-backup-20261022-memory-safe/databases`;
private configuration also copied and hashed. The original 0.4.0 package remains
preserved, and a reconstruction of the currently installed 0.5.0 payload is
retained for rollback. A further stopped-store backup containing both completed
installed studies was created and verified at
`apps/desktop/release/acceptance-0.5.0/installed-completed-studies`. Services are
now running normally after relaunch. No production restore or deletion occurred.

### Five highest-value changes and observed defects

1. **Critical: prevent host OOM.** Reproduce: preflight the native coder pack
   with the old defaults on this 32 GiB host. Observed: a 23.42 GiB pinned arena
   continued despite a warning; Linux killed Strata and the runtime stopped.
   Expected: reject unsafe memory use before launch. Impact: desktop disruption
   and lost test progress. Fixed with file-backed experts, a RAM reserve and
   rejection of old unsafe plans. Kernel/process evidence is recorded in the
   implementation log; no screenshot of the OOM itself was captured.
2. **Major: produce honest, usable measurements.** Reproduce: run either model
   with automatic reasoning, then repeat a Strata prompt. Observed: no answer
   text inside the cap; later Strata reuse inflated prefill. Expected: explicit
   shared answer policy and fresh prompt processing. Impact: unavailable or
   misleading comparisons. Fixed with explicit policy, usage requests, cache
   reset/reuse rejection and observed native JSON parsing. Screenshots:
   `../apps/desktop/release/acceptance-0.5.0/lab-unavailable-explained.png` and
   `../apps/desktop/release/acceptance-0.5.0/lab-strata-measured-complete.png`.
3. **Major: recover from startup/preflight failures.** Reproduce: start Strata
   without its required profile/cache or use the old registry keys. Observed:
   preflight could not reach real execution. Expected: trusted executable IDs,
   discovered supporting files and a clear retry state. Impact: every study
   blocked. Fixed registry/recovery plus bounded shipped-profile discovery and
   defaults; final real preflight passed. Screenshot:
   `../apps/desktop/release/acceptance-0.5.0/lab-strata-profile-required.png`.
4. **Major: make cancellation reliable.** Reproduce: cancel a running study in
   Electron. Old prompt-based path was unsupported. Expected: a usable dialog,
   visible request state and owned-process cleanup. Impact: user cannot stop
   expensive work. Fixed; real UI run reached Cancelled. Screenshots:
   `../apps/desktop/release/acceptance-0.5.0/lab-real-cancel-dialog.png` and
   `../apps/desktop/release/acceptance-0.5.0/lab-real-cancelled.png`.
5. **Major: retain setup and explain hardware choices.** Reproduce: relaunch
   after verification and check engine updates. Expected: reuse unchanged hashes
   and show an actionable hardware recommendation. Impact: repeated waits and
   uncertainty about downloads. Verified ten models retained hashes; actual
   final Settings displayed two Recommended for your hardware badges with GPU,
   driver and selected assets. No engine download/install was clicked.
   Screenshot: `../apps/desktop/release/acceptance-0.5.0/lab-final-settings-recommendations.png`.

Minor polish fixed: evidence tables no longer squeeze words into single letters;
parameters use disclosure; finished trial state follows observations. Remaining
polish: Compare still displays immutable proposal state in its provenance table,
work-unit totals can remain unknown, and some qualification codes need plainer
wording. These do not turn an ineligible result into a winner.

Candid verdict: a nontechnical user can now complete folder setup and a small
real test without API setup on this host. Advanced qualification and recovery
still use technical language and would benefit from help. No major blocker
remains in the tested 4K configurations. Other model/context combinations,
new engine upgrades, clean-host installation and validated recipes are untested.

### Acceptance and rollback

All requested local journey gates completed: launch, existing-folder setup,
hardware/recommendations, verified model reuse, real preflight and measurements
for both engines, real cancellation, saved comparisons, native Close/Cancel,
Minimize/reopen, Quit with service shutdown, relaunch and persistence. Native
folder-picker Cancel is operator-confirmed; its trace returned selected, so an
independent native Cancel result is not claimed. Changed/missing/unreadable and
interrupted hash verification were tested offline without modifying real models.

To roll back the application, Quit it using the UI and confirm its services have
stopped, then install the preserved package:

```bash
pkexec dpkg -i apps/desktop/release/upgrade-backup-20261022-memory-safe/previous-installed-0.5.0-repacked.deb
```

This reconstructed previous payload has SHA-256
`019f2dd17cd24e78785ef97137d9ffa655ac7436b1f16a631cd591cf43ae624e`.
No schema migration was added. Retain current stores; a database restore is not
part of ordinary application rollback. Verified pre-upgrade and final backups
remain available if a separate stopped-store recovery is ever needed. The
original 0.4.0 package is also preserved. Rollback itself was not exercised.

Historical evidence below predates this final acceptance section.

---


Status: operator authorized the upgrade and two real tests (Strata and llama.cpp).
0.5.0 was installed over 0.4.0 and all 7,897 installed payload files matched the
actual package. A refreshed 0.5.0 candidate adds the observed trial-failure and
Strata preflight fixes; its installed acceptance is pending. No engine/model
downloads, engine installation/removal, driver changes or original-study retries
were performed.

## Delivered fixes

- Register discovered engine binaries by executable identity; reject conflicting
  registrations and retain path/hash checks.
- Failed/rejected/exhausted preflight commands become blocked with a safe reason
  and Retry preflight. Duplicate results remain idempotent; cancellation is not
  overwritten by late failures. Retrying clears the old completion timestamp.
- Busy workers do not acquire extra execution work that they cannot run.
  Cancellation commands remain pollable, and a local completion race retains
  rather than discards an acknowledged lease.
- Cancel test uses a keyboard-accessible dialog, optional reason, pending state
  and visible request errors. It no longer calls Electron's unsupported prompt.
- Unchanged model hashes survive restart; changed, missing and unreadable files
  lose verification. Interrupted verification preserves completed hashes and
  reports unfinished work. Services running and execution readiness are distinct.
- Hardware recommendations appear in Settings and the startup dialog with the
  selected asset, GPU, driver and explanation. The RTX 3060/595.99.02 fixture
  selects llama.cpp CUDA 12.8 rather than incompatible CUDA 13.4; Strata CUDA 13
  matches its declared minimum. Unknown compatibility remains explicit.
- Dialogs use theme colors, trap keyboard focus, support Escape, and scroll.
  Warnings summarize common conditions and omit external process arguments.
- Small setup test sets one 4K context, one candidate/finalist, one screening
  replication and two final replications, retaining qualification and GPU safety.
  Planning is labelled ready to submit; real readiness still requires preflight.
- Shutdown continues stopping the optimizer/controller even if worker recovery
  raises an error, then reports the failure.
- Native folder pickers attach to the requesting window. Bounded private
  `desktop-events.log` files record request IDs, picker stages and elapsed time
  without paths, tokens or process arguments. Busy errors explain that the
  existing picker/setup operation must be finished or cancelled.
- Finished studies with only invalid observations explicitly say they contain
  no valid measurements. Per-trial failures explain contention/memory failures
  without rendering full process arguments.
- Strata uses its existing worker-owned serving wrapper for allocation checks,
  with a quiet-GPU check, exclusive lease, generated sandbox profile, actual
  effective-context comparison, cancellation/renewal and guaranteed cleanup.
  Missing/undersized contexts cannot pass; candidate serving and qualification
  checks remain mandatory. This replaces the unconditional Inconclusive result
  that prevented every Strata study from starting.

## Evidence and limits

The packaged sandboxed Electron candidate used temporary application data and
a 168-byte synthetic GGUF metadata fixture, with the existing engine parent
read-only. Automatic discovery, verification, selected build persistence and
verified inventory after relaunch were observed. No inference ran on that file.

Actual packaged UI: both hardware recommendation badges and selected assets
were visible; expanded startup dialog had no horizontal overflow; Escape closed
it after Review updates. Light/dark contrast was inspected. The supported Cancel
dialog was exercised against explicitly labelled demo data: Keep running
dismissed it and Cancel test produced Cancelled. This proves the packaged
renderer dialog, not live engine cancellation.

Operator reported completion of native Close → Cancel, Close → Minimize to tray,
reopen from Show operator console, and Quit. These are operator-assisted results,
not independent automation observations. The initial parentless picker remained
pending, and a subsequent click produced “Another local runtime operation is in
progress.” After attaching the picker to its parent, Playwright observed the
real native call return one selected directory (not a mocked response); the UI
added that parent folder, discovered 11 models and started verification. This
was operator-assisted native selection. The temporary large verification pass
was stopped via its own supervisor; its children exited. The installed window
lifecycle repeat is pending operator actions recorded to a temporary event log.

During the first native lifecycle session, the build staging directory was
replaced while the candidate was open. A lazy worker-journal import then failed
on Quit and left two temporary services. Their temporary-profile database paths
were verified before stopping only those processes. This is a test-procedure
contamination, not evidence that the stable installed payload lacks the module.
It exposed the shutdown robustness issue fixed above. Final candidate checks
use a stable build directory. Mocked native dialog choices in the lifecycle
smoke script do not count as native acceptance.

Screenshots (local release artifacts):

- `apps/desktop/release/acceptance-0.5.0/recommendations.png`
- `apps/desktop/release/acceptance-0.5.0/cancel-dialog.png`
- `apps/desktop/release/acceptance-0.5.0/modal-dark.png`
- `apps/desktop/release/acceptance-0.5.0/folder-selection.png`
- `apps/desktop/release/acceptance-0.5.0/desktop-events.log`
- `apps/desktop/release/acceptance-0.5.0/llama-no-measurements.png`
- `apps/desktop/release/acceptance-0.5.0/strata-initial-preflight-blocked.png`
- `apps/desktop/release/acceptance-0.5.0/compare.png`

## Installed real attempts

The installed 0.5.0 reused both engine selections and all 10 verified models on
startup. The setup wizard was saved through the UI. Both new studies used one
4K context, one candidate, one finalist, one screening replication and two final
replications, with quiet-GPU and full-context requirements enabled.

- llama.cpp build 701, Gemma 12B Q4_0 (6.5 GiB):
  `exp_e570132a-6835-5a30-bec1-3752e54adcea`. Real preflight passed a 4096-context
  CPU server allocation check. Both GPU trials were rejected as
  EXTERNAL_GPU_CONTENTION; zero retained samples, no throughput/latency result,
  no validated winner. The controller finished processing the study. Compare
  correctly shows ineligible evidence and no paired scores. “Completed” alone
  must not be interpreted as a successful benchmark.
- Strata 0.1.44.1, coder IQ1_M pack (79.2 GiB including source files):
  `exp_e41c8a9f-57a3-54c8-932d-cb33cf361b7e`. Preflight blocked because the old
  implementation always returned Inconclusive for Strata. Retry preflight is
  visible. No measurement ran. The refreshed candidate implements a managed
  allocation probe; its live validation is still required.

The original assessment's cancelled study remains untouched. Other GPU processes
were not interrupted, allowlists were not expanded and safeguards were not
disabled. Remaining gates: refreshed-package installation, valid real
measurements on a quiet GPU, live worker cancellation acceptance and final
installed-profile lifecycle/persistence. No validated recipe or successful real
benchmark is claimed.

## Candidate and rollback

Package: `apps/desktop/release/ai-inference-lab-desktop_0.5.0_amd64.deb`

Refreshed candidate SHA-256:
`a31aec89a938fc1ad15d504ac355541748252b2dfb3f57b2be2f686ff4c3fe4e`.
The first installed 0.5.0 payload had SHA-256
`a444be9726952135919cc1f04840b8de24dc6767cbc068e38caee816b716cb4d`.

Extracting the actual package and comparing bytes confirmed all 102 Python
source files and all built renderer files match the tested source/build.

Verified pre-upgrade backup: `apps/desktop/release/upgrade-backup-20261022-final/databases`.
The backup verifier passed SHA-256, sizes and SQLite integrity checks for both
stores. Relevant configuration, local enrollment/hash cache and renderer
preferences are preserved under the sibling `profile` directory. These contain
private configuration and should remain local. Previous 0.4.0 package is retained
in `apps/desktop/release/upgrade-backup-20261022` (SHA-256
`dc464b55f08e8ae4a4190a352e619c6341bb20f6587d2a658d6c37909deff7a5`).

Before upgrading, ensure the installed app and all its own services are stopped;
revalidate backups and refresh them if original data changed. Install only after
approval. Roll back by cleanly quitting 0.5.0 and reinstalling the preserved
0.4.0 package. No new database migration is introduced by these fixes. If store
restoration is necessary, stop services, preserve the current data, verify the
backup, and use the offline restore CLI independently for controller and
optimizer as documented in RUNBOOK section 9. Never delete the only copy or
restore over running services. No rollback or production restore has been run.
