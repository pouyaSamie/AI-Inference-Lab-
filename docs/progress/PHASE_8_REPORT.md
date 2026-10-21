# Phase 8 report — offline hardening increment (partial)

Date: 2026-10-21.

## Outcome

Phase 8 is **partial**. The phase exit gate — end-to-end acceptance with pinned
manifests on target hosts — is **not met**. No systemd unit, `.deb`, database
restore or unowned GPU process was touched, and no real engine/model/preflight
run was performed.

This increment delivers the parts that can be verified safely offline:

- credential-scope and disabled-worker security regression tests;
- a verified two-store SQLite backup/verify/restore helper and operator CLI;
- a deterministic, non-flaky recipe-qualification fixture;
- an installation/upgrade/rollback/restore/uninstall runbook;
- an honest AC-01…AC-44 acceptance matrix;
- documentation of the remaining live gates.

Live installation, GUI, hardware-matrix, concurrency/latency/telemetry and real
A/B acceptance remain blocked on operator approval and target hardware.

## Delivered

### Security hardening

`tests/test_security_hardening.py` adds three tests:

1. `/health` and `/ready` are public; operator routes reject missing or
   non-Bearer credentials with `401` and do not echo the supplied credential.
2. Worker, optimizer and operator tokens are scoped: a worker token gets `403`
   on operator routes, the operator token gets `403` on worker polling, an
   optimizer token gets `403` on operator routes, and enrollment requires the
   separate enrollment header.
3. A disabled worker token cannot poll, heartbeat or read its snapshot (`401`).

These complement the existing Electron IPC/navigation tests and the release
import immutability test. They do not replace a full security audit or a live
network/egress test.

### Backup and restore

Added:

- `python/lab_api/lab_api/backup.py` — SQLite online backup, manifest
  SHA-256/size verification, `PRAGMA integrity_check`, and restore with a
  pre-restore snapshot. Existing targets require `replace=True`; active
  `-wal`/`-shm` sidecars are refused.
- `scripts/backup_databases.py` — `backup`, `verify` and `restore` subcommands
  for the separate controller and optimizer databases.
- `tests/test_backup.py` — four tests covering two-store backup/verify/restore,
  tamper detection, existing-target preservation, unsafe labels and sidecar
  rejection.

The CLI was exercised on temporary SQLite files only:

```text
backup  -> controller.sqlite3 + optimizer.sqlite3 + manifest.json
verify  -> manifest returned and both digests matched
restore -> restored.sqlite3 contained the original row
```

No production database was opened or replaced.

### Fixture reliability

The existing synthetic measured-recipe test could produce a candidate slower
than its baseline and then fail its expected `201`, despite scaling candidate
metrics. It now derives candidate samples from the paired baseline samples
(baseline × 1.5) instead of assuming the simulated candidate was already near
baseline. Ten consecutive runs passed. This changes test data construction, not
qualification logic.

### Runbook and acceptance matrix

- `docs/RUNBOOK.md` covers preflight, pinned checkout/install, systemd (approval),
  enrollment, desktop package (approval), backup, upgrade/rollback, restore,
  uninstall/data retention, security checks and the live acceptance record
  required before claiming v1.
- `docs/ACCEPTANCE_MATRIX.md` maps AC-01…AC-44 to offline evidence, partial
  implementation or blocked live proof. The matrix explicitly records the
  unmet exit gate.

### Documentation

Added `docs/ADR/0018-offline-sqlite-backup-restore.md` and updated
`AGENTS.md`, `README.md`, `docs/ARCHITECTURE.md`,
`docs/IMPLEMENTATION_STATUS.md` and `docs/NEXT_STEPS.md`.

## Verification actually run

```bash
uv run ruff format --check
# 122 files already formatted

uv run ruff check
# All checks passed!

uv run mypy python
# Success: no issues found in 98 source files

uv run pytest -q
# 73 passed in 11.72s (repeated three times: 73 passed each run)

uv run python scripts/check_contracts.py
# contracts are current

pnpm typecheck
# generated contracts + desktop renderer/Electron typecheck passed

npm --prefix apps/desktop test -- --run
# 9 test files, 29 tests passed

npm --prefix apps/desktop run build
# production renderer + Electron build passed
# dist/assets/index-CQZMYOhX.js 336.50 kB (gzip 97.12 kB)

npm --prefix apps/desktop run package:linux
# built ai-inference-lab-desktop_0.1.0_amd64.deb (84.0 MiB)
# 88,126,518 bytes
# sha256 7778d186170beb4ed978726fc15900ea0bb669b9b9515f00ffa72084a8ba7d1f

systemd-analyze verify packaging/systemd/lab-*.service
# parsed all units; only the expected missing deployed executables:
# /opt/ai-inference-lab/.venv/bin/lab-{api,optimizer,worker}
```

The `.deb` was rebuilt after the Phase 7 commit; its current byte size/hash is
recorded above. It was not installed. The same package boundary (no
data-deleting maintainer script) remains.

## Not delivered / blocked

- `.deb` installation, upgrade/rollback, signing and AppImage packaging.
- systemd installation, boot/logout survival and GPU device-permission test.
- Full GUI run against a live controller/worker and a packaged Electron session.
- Full ~270 GiB model/source-shard hash scan.
- Real preflight, low-impact trial, near-capacity/full-context serving proof and
  Strata full-context proof (`INCONCLUSIVE`).
- RTX 3060 long-context and L40S hardware matrix.
- Real measured release A/B against an installed candidate.
- AC-15 injected quality failure, AC-28 mock future adapter, AC-31 1,000-write
  load, AC-33 latency measurement, AC-38 OOM-learning proof, AC-42 24-hour
  telemetry retention, and AC-44 boot test.
- A committed desktop lockfile and reproducible clean desktop install.

## Approval gates

Before any of the following, obtain explicit operator approval and a verified
backup/rollback plan:

1. install/enable systemd units or install the `.deb`;
2. run a full model hash scan or a real preflight/trial;
3. run a multi-context benchmark campaign;
4. restore a production database;
5. sign/publish release artifacts or acquire AppImage tooling;
6. terminate any process not owned by the worker.

No such action was taken in this increment.
