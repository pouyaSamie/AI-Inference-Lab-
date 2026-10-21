# Acceptance matrix — offline evidence and blocking live gates

Last updated: 2026-10-21.

This matrix maps the PRD acceptance criteria to evidence that exists in this
repository. It deliberately separates **offline verification** from **live
acceptance**. A passing unit/integration test is not a real engine measurement,
a packaged `.deb` is not an installation, and a simulated run is not hardware
qualification.

Status legend:

- **Verified offline** — a committed automated check exercises the stated
  boundary without a GPU, installed engine or live operator session.
- **Partial** — implementation and/or offline checks exist, but a required live
  or packaged-host condition was not exercised.
- **Authored only** — install/runbook/unit artifacts exist; no privileged action
  was performed.
- **Blocked** — needs hardware, an approved candidate, a live GUI or a
  privileged installation that was not authorized.
- **Not demonstrated** — no evidence in this workspace.

The Phase 8 exit gate (**end-to-end acceptance on target hosts with pinned
manifests**) is **not met**. See `docs/progress/PHASE_8_REPORT.md`.

| AC | Status | Evidence / boundary |
|---|---|---|
| AC-01 | Blocked | Controller-owned jobs do not depend on the Electron window; the live close/exit/systemd scenario has not been run. |
| AC-02 | Authored only | Three systemd units and `packaging/systemd/README.md` exist. `systemd-analyze verify` parses them; they are not installed or boot-tested. |
| AC-03 | Partial | Local `.deb` built and inspected; no install, upgrade or AppImage build. |
| AC-04 | Verified offline | Adapter/conformance fixtures and real-worker inventory distinguish llama.cpp and Strata with pinned executable hashes. |
| AC-05 | Verified offline | Golden help/version fixtures reject unobserved or changed flags; no invented flags are emitted. |
| AC-06 | Verified offline | API/UI tests cover objectives, six context values and three search depths; the Optimize wizard submits through generated contracts. |
| AC-07 | Verified offline | Search-policy/budget tests cap distinct candidates and finalists; repetitions are budgeted separately. |
| AC-08 | Verified offline | Simulated infeasible contexts produce explicit `INFEASIBLE`/`UNSUPPORTED`; no fabricated 128K score. No real 128K run exists. |
| AC-09 | Verified offline | Workload/context tests enforce tokenizer-fitted input, generated tokens and no silent truncation. No real serving proof exists. |
| AC-10 | Verified offline | Adapter and workload tests keep native bench metrics separate from serving/TTFT evidence. |
| AC-11 | Verified offline | `tests/test_finalization.py` recomputes scores/intervals and never promotes inconclusive evidence. |
| AC-12 | Partial | Worker tests cover per-UUID lease locks and unowned-process boundaries; no live simultaneous GPU job test. |
| AC-13 | Verified offline | Resilience tests cover expired leases, replay-safe completion and conflicts; live worker death/API restart/OOM not exercised. |
| AC-14 | Partial | Simulated runs cover selected contexts and skipped reasons; no real full matrix exists. |
| AC-15 | Not demonstrated | The quality-gate implementation exists, but no test injects an intentional quantized-KV recall failure. |
| AC-16 | Verified offline | Finalization tests keep rankings per context and refuse screening-only winners. |
| AC-17 | Verified offline | Cross-context tests require complete coverage and compare the geomean reference calculation. |
| AC-18 | Partial | Recipe construction/verification is tested offline; no real verified recipe has been launched. |
| AC-19 | Partial | Strata source shards are resolved read-only and full-context proof is explicitly `INCONCLUSIVE`; no real Strata serving run. |
| AC-20 | Verified offline | `tests/test_updates.py` and `tests/test_api_releases.py` cover offline import, assessment and A/B proposal without changing installed artifacts. |
| AC-21 | Verified offline | Synthetic regression evidence is detected and `upgrade_approved` stays false. No real candidate A/B exists. |
| AC-22 | Verified offline | `apps/desktop/electron/security.test.ts` and `api-proxy.test.ts` cover IPC validation, navigation and URL boundaries. |
| AC-23 | Partial | Release code is offline and no updater exists; a blocked-egress end-to-end run was not performed. |
| AC-24 | Verified offline | `tests/test_security_hardening.py` proves operator/worker/optimizer credential scoping and disabled-worker rejection. |
| AC-25 | Not demonstrated | Browser companion is optional and not implemented. |
| AC-26 | Partial | Simulated controller/optimizer recovery tests pass; live worker-journal reconciliation after a real restart is not run. |
| AC-27 | Blocked | RTX 3060 is observed; no L40S and no representative live long-context run. |
| AC-28 | Not demonstrated | No mock future adapter registration/recipe test exists. |
| AC-29 | Partial | Recipe export/validation contracts exist; no real recipe has complete runnable launch evidence. |
| AC-30 | Partial | The desktop package has no data-deleting maintainer script, but install/uninstall retention was not executed. |
| AC-31 | Not demonstrated | No 1,000-event concurrent SQLite/optimizer load test exists. |
| AC-32 | Verified offline | Optimizer ask/tell replay and reconciliation tests pass; no process-kill-between-commit-and-tell test. |
| AC-33 | Not demonstrated | No FastAPI p50/SSE-lag measurement under active TPE plus 1,000 bootstrap resamples. |
| AC-34 | Verified offline | Worker protocol is outbound polling with idempotent ack; no external inbound-block firewall test. |
| AC-35 | Verified offline | `tests/test_api_flow.py` proves stale/missing inventory returns `202 PREFLIGHT_REQUIRED` and queues `SCAN`. |
| AC-36 | Verified offline | Static import policy and adapter test forbid subprocess/network/filesystem I/O; malformed fixtures are covered. |
| AC-37 | Partial | Near-capacity harness and labels exist; no real candidate allocation-failure proof. |
| AC-38 | Not demonstrated | Feasibility structures exist, but no repeated resource-infeasible proposal test proves pruning/independence. |
| AC-39 | Partial | Electron disables acceleration before ready in code; no reference-host GPU contamination test. |
| AC-40 | Partial | Token persistence is keyring-only with session fallback in code; no locked-keyring/`basic_text` live test. |
| AC-41 | Verified offline | SSE replay, ordering/dedup and `EVENT_GAP` refresh are covered by API/UI tests. |
| AC-42 | Not demonstrated | No 24-hour telemetry retention/WAL-growth test. |
| AC-43 | Verified offline | Offline contract export and `scripts/check_contracts.py` drift gate pass. |
| AC-44 | Authored only | Systemd units are authored; no boot/logout/GPU-device-permission test. |

## Reproducible offline gates

```bash
uv run ruff format --check
uv run ruff check
uv run mypy python
uv run pytest -q
uv run python scripts/check_contracts.py
pnpm typecheck
npm --prefix apps/desktop test
npm --prefix apps/desktop run build
npm --prefix apps/desktop run package:linux
systemd-analyze verify packaging/systemd/lab-*.service
```

These gates do not close AC-01/02/03/14/15/18/19/23/26/27/28/29/30/31/33/37/38/39/40/42/44.
Closing them requires the live acceptance and approval steps in
`docs/RUNBOOK.md`.
