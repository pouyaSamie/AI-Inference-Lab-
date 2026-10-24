# Production-readiness work — 2026-10-23

Status: **release candidate in development; not a production-readiness claim**.
Target: local Linux desktop with the existing RTX 3060, llama.cpp and Strata
builds. Clean-host certification, systemd deployment and other GPU families
remain separate acceptance gates.

## Implemented and verified before the serving increment

- Fixed recipe timestamp serialization across SQLite sessions. Create, list,
  filtered list, get and idempotent re-creation have regression coverage.
- Scoped optimizer study identity to its experiment. The same immutable plan
  can be submitted after completion/cancellation with a fresh idempotency key;
  same-key replay preserves the original study and history.
- Fixed Recipes loading/error recovery, persisted validation status display,
  recorded context/scope and asynchronous verification result tracking.
- Source validation: 124 Python tests and 81 desktop tests passed for this
  increment; Python/TypeScript checks, lint, format and contract drift passed.
  A 0.5.1 package was built but not installed.
- A copied saved-work profile opened the existing validated Strata recipe and
  completed real worker identity verification. Original stores were unchanged.

## Operator-requested 0.6.0 scope

The operator explicitly requested engine launch from best recipes, with both
built-in chat and an endpoint for other applications. This extends the earlier
assessment/fix scope to managed local serving.

Implemented candidate behavior:

- Authenticated run/stop/chat endpoints enqueue frozen, typed outbound worker
  commands. Renderer isolation and token boundaries remain intact.
- Only persisted validated recipes can launch. Candidate/model/build identities
  are checked; all model files are rehashed with byte/file progress. Strata's
  wrapper and native profile identity are checked as well.
- One worker-owned session, separate loopback port, exclusive Lab GPU flock,
  journaled process group, readiness + one-token smoke and context verification.
  Late Stop requests cannot stop replacement sessions. Shutdown stops owned
  processes; no automatic recipe restart occurs after relaunch.
- Built-in text chat uses the same worker session, bounded requests/responses,
  target-engine token counting, no silent context truncation, and no benchmark
  observations or qualification changes. Messages stay on this machine and are
  retained in the local durable command store; they are not logged as diagnostics.
- Current serving health is stored separately from immutable snapshots. The
  additive controller migration is `c712e4d509ab`. Both stores are snapshotted
  before migration by the packaged runtime. Optimizer schema is unchanged.
- Local configuration/build changes and new benchmarks are blocked while a
  recipe session is active. Old unimplemented promotion/prompt controls were
  replaced in the UI. Legacy Strata metadata exports are explicitly not
  advertised as standalone executable scripts; managed Run regenerates the
  native profile from the retained candidate.

## Evidence so far

- 141 Python tests, 83 desktop tests, mypy (105 files), TypeScript, Ruff, format,
  contract drift and build pass. Fifteen serving cases use tiny fake HTTP
  executables for both adapter families, including changed files, GPU conflict,
  failed context smoke, context overflow, stale Stop, startup/Stop races and
  release of the GPU only after process shutdown. These are offline tests, not
  real engine performance evidence.
- Ten packaged runtime tests pass. Packaged startup reports 0.6.0, visible UI,
  renderer Node unavailable and sandbox enabled. An initial CDP startup-context
  race was fixed with a narrowly bounded retry in the smoke harness; rerun passes.
- The copied real stores migrated with all nine studies intact (six completed,
  two cancelled, one blocked). Two pre-migration store snapshots were created.
- Actual UI Run on the saved Strata recipe progressed through 85,040,157,676
  bytes / 13 files, then refused launch because of external GPU compute use.
  GNOME desktop portal PID 658411 was identified read-only. No unrelated helper
  was stopped and no benchmark safeguard was weakened. Real server/chat
  acceptance is pending the operator's serving-mode choice.
- Evidence directory: `apps/desktop/release/acceptance-0.6.0/`.

## Release gates still required

1. Resolve the explicit serving-only shared/exclusive GPU policy, retaining
   exclusive/quiet benchmark qualification. Repeat real Run, chat, external
   endpoint, Stop and failure/retry checks.
2. Exercise native Close/Cancel/Minimize/reopen/Quit while serving; confirm owned
   process shutdown and no automatic engine restart after relaunch.
3. Verify a freshly built final package, SHA-256 and bundled source payload.
   Preserve the currently installed package and stopped-store/config backups.
4. Obtain explicit operator approval before installation (AGENTS.md requires it).
   Verify installed bytes and repeat saved-state and serving acceptance.
5. Clean-host installation and rollback/restore rehearsal with temporary stores;
   extended stability/resource-pressure testing, support scope and release
   signing/distribution policy. No production database restore or systemd
   installation is authorized by this checklist.

A successful 4K benchmark qualifies a performance recipe for that exact evidence
scope. It does not certify answer quality, longer contexts, all hardware, external
production deployment or unattended operation. Earlier cancelled assessment work
must remain cancelled.

## Current reviewable candidate

`apps/desktop/release/ai-inference-lab-desktop_0.6.0_amd64.deb`

SHA-256: `d4cf46f979b4b34cc56bb39065ea87a418dfd104bb9feb63d3b6e3290b0be77a`.

The final extracted package byte-matches the source for the serving worker,
controller routes, recipe/study fixes, command recovery and frozen serving
contracts. The packaged renderer contains Run/Chat controls and corrected recipe
status. Exact hashes and logs are in the evidence directory. No package was
installed in this increment.

Final UI recovery check used another fresh temporary copy: **Run recipe** and
then **Retry** each created one command. Both failed safely with the GPU-busy
message before model hashing (0 bytes) or engine launch. No cancelled benchmark
was retried. A separate earlier draft demonstrated full-file progress before
the same safety refusal; the final candidate adds an early GPU check to avoid
that wasted wait. No real chat/endpoint success is claimed.

Temporary-store migration/rollback rehearsal passed: all nine experiment IDs and
states remained identical; both newer stores were backed up and verified before
restoring the old snapshots to temporary targets. The initial rollback attempt
correctly refused an open WAL sidecar; after the rehearsal process exited, the
stopped-store restore succeeded. Original production stores were untouched.

The operator's shared/exclusive serving-mode choice is still pending. Exclusive
mode remains enforced. A normal signal did not exit the temporary app; the Playwright harness then
called Electron app.exit, allowing parent-EOF service cleanup. A process check
confirmed no processes remained for any temporary saved-work profile. This
is a test-harness cleanup, **not native Quit acceptance**. Native lifecycle with
a running engine remains a gate.
