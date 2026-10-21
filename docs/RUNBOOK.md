# Operations runbook — install, upgrade, restore and acceptance

Status: **authored and tested only offline.** No command in this runbook was
executed with elevated privileges on this host. Installing units or a `.deb`,
replacing a live database and uninstalling are explicit operator actions.

This runbook assumes the repository is checked out at
`/opt/ai-inference-lab`, the controller/optimizer/worker run as `ailab`, systemd
is used, and engine/model roots are configured in
`/etc/ai-inference-lab/lab.env`. Adjust paths for the host; never point a model
or engine root at a writable worker location.

## 1. Data that must survive an upgrade or uninstall

| Data | Default location | Owner | Delete only on explicit request |
|---|---|---|---|
| Controller SQLite | `/var/lib/ai-inference-lab/controller.sqlite3` | `ailab` | yes |
| Optuna SQLite | `/var/lib/ai-inference-lab/optuna.sqlite3` | `ailab` | yes |
| Worker state, journal, sandbox, hash cache | `/var/lib/ai-inference-lab/worker` | `ailab` | yes |
| Worker credential | root-only secret file / credential unit | `root` | yes |
| Engine binaries, model weights | operator-managed roots | operator | never by this project |
| Desktop token | OS keyring; otherwise session memory | desktop user | via Settings only |

The desktop package does not contain a `prerm`/`postrm` that deletes controller
databases, worker state, model files or engine binaries. Removing the desktop
package must never remove benchmark evidence or inference assets.

## 2. Host preflight

```bash
uname -a
python3 --version
uv --version
nvidia-smi --query-gpu=index,name,uuid,memory.total,driver_version --format=csv
df -h /var/lib/ai-inference-lab /opt/ai-inference-lab
```

Confirm:

- Python 3.12+ and `uv` are available;
- the `ailab` user exists and cannot write to engine/model roots;
- the controller and optimizer database paths are different files;
- the GPU UUID intended for benchmarks is not already used by an unowned
  inference process;
- no process outside the worker's journal will be terminated by this project.

## 3. Install the backend from a pinned checkout

```bash
sudo install -d -o ailab -g ailab /opt/ai-inference-lab /var/lib/ai-inference-lab
sudo -u ailab git -C /opt/ai-inference-lab fetch --all --tags
sudo -u ailab git -C /opt/ai-inference-lab checkout <pinned-commit-or-tag>
sudo -u ailab sh -c 'cd /opt/ai-inference-lab && uv sync --all-packages'
```

Create the environment file:

```bash
sudo install -d -m 0750 -o root -g ailab /etc/ai-inference-lab
sudo install -m 0640 -o root -g ailab \
  /opt/ai-inference-lab/packaging/systemd/lab.env.example \
  /etc/ai-inference-lab/lab.env
sudoedit /etc/ai-inference-lab/lab.env
```

Replace every `CHANGE_ME`, use independent high-entropy secrets and keep the
controller and optimizer database URLs distinct. Do not commit this file.

Run the migration explicitly before starting the service:

```bash
cd /opt/ai-inference-lab
sudo -u ailab uv run --env-file /etc/ai-inference-lab/lab.env alembic upgrade head
```

## 4. systemd installation (approval required)

Review the units first. They use `NoNewPrivileges`, a strict filesystem view,
an unprivileged user and no inbound worker port. Confirm the GPU `DeviceAllow`
entries match this host.

```bash
sudo install -m 0644 /opt/ai-inference-lab/packaging/systemd/lab-*.service \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lab-controller.service
sudo systemctl enable --now lab-optimizer.service
sudo systemctl enable --now lab-worker.service
systemctl status lab-controller.service lab-optimizer.service lab-worker.service
journalctl -u lab-controller -u lab-optimizer -u lab-worker --since today
```

Do not enable the worker on a host whose GPU is occupied by an unrelated live
service. The worker never adopts or kills an unowned process.

## 5. Worker enrollment

Enrollment is a one-time privileged operation. The returned worker token is
shown once; store it root-only and never place it in a unit file or shell
history.

```bash
sudo -u ailab env LAB_ENROLLMENT_TOKEN='<scoped-enrollment-token>' \
  lab-worker --enroll
```

Then start the worker. Verify it registered without exposing the token:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS -H "Authorization: Bearer $LAB_OPERATOR_TOKEN" \
  http://127.0.0.1:8000/api/v1/workers
```

A revoked/disabled worker must receive `401` and cannot poll, heartbeat or read
its snapshot. A worker credential must receive `403` on operator routes.

## 6. Desktop installation (approval required)

```bash
sudo apt-get install --no-install-recommends \
  ./apps/desktop/release/ai-inference-lab-desktop_0.1.0_amd64.deb
```

The package installs under `/opt/ai-inference-lab/desktop`, fixes the
`chrome-sandbox` mode in `postinst`, and does not touch benchmark data. Launch
it normally:

```bash
ai-inference-lab
```

Verify the renderer has no Node integration, uses `lab://app` with CSP, and
shows `OFFLINE DEMO MODE` only when intentionally in demo mode. Store the
operator token through Settings; if the keyring backend is `basic_text` or
unavailable, the token remains session-only.

## 7. Backup before every upgrade

All services may stay running for a backup because SQLite's online backup API is
used. Use a new destination directory; existing directories are refused.

```bash
cd /opt/ai-inference-lab
sudo -u ailab uv run python scripts/backup_databases.py backup \
  --controller /var/lib/ai-inference-lab/controller.sqlite3 \
  --optimizer /var/lib/ai-inference-lab/optuna.sqlite3 \
  --output /var/backups/ai-inference-lab/$(date -u +%Y%m%dT%H%M%SZ)
```

The command writes `manifest.json`, prints its verified contents and stores
mode `0600` copies. Verify independently later:

```bash
uv run python scripts/backup_databases.py verify \
  --backup /var/backups/ai-inference-lab/<timestamp>
```

Copy the backup off-host through the operator's approved backup mechanism. A
backup manifest contains only file basenames, sizes and SHA-256 digests.

## 8. Upgrade sequence

1. Review the release notice in the Updates screen. Do not fetch or install an
   engine from the UI.
2. Record the current commit/tag and `.deb` SHA-256.
3. Create and verify a backup (section 7).
4. Stop the controller and optimizer. Stop the worker only if its state layout
   or installed engine/model identity is being changed. Never kill unowned
   inference processes.

```bash
sudo systemctl stop lab-controller.service lab-optimizer.service
# Stop the worker only when the upgrade requires it:
sudo systemctl stop lab-worker.service
```

5. Check out the pinned commit and run `uv sync --all-packages`.
6. Run `alembic upgrade head` with the production environment file.
7. Start controller and optimizer. Verify `/ready`, `/api/v1/status` and the
   optimizer heartbeat.
8. Start the worker and wait for a fresh snapshot. Do not reuse a snapshot whose
   engine/model hashes no longer match.
9. Install the desktop `.deb` only if the desktop changed.
10. Run the acceptance checks in section 11 before approving any candidate
    engine update.

### Rollback

Use the previously pinned checkout and prior `.deb`, then restart services:

```bash
sudo systemctl stop lab-controller.service lab-optimizer.service lab-worker.service
sudo -u ailab git -C /opt/ai-inference-lab checkout <previous-pinned-commit>
sudo -u ailab sh -c 'cd /opt/ai-inference-lab && uv sync --all-packages'
sudo systemctl start lab-controller.service lab-optimizer.service
sudo systemctl start lab-worker.service
```

Alembic migrations are forward-only by policy. If a rollback requires schema
restoration, stop all services and restore the controller database as in
section 9. Never run a destructive downgrade against the only copy.

The desktop can be rolled back by installing the previous `.deb`; user data
and controller evidence are unaffected.

## 9. Database restore

**Stop controller, optimizer and worker first.** Do not restore under a running
process. Remove/checkpoint any stale SQLite `-wal`/`-shm` sidecars before
restoring; the restore helper refuses active sidecars.

```bash
sudo systemctl stop lab-controller.service lab-optimizer.service lab-worker.service
cd /opt/ai-inference-lab
sudo -u ailab uv run python scripts/backup_databases.py verify \
  --backup /var/backups/ai-inference-lab/<timestamp>
sudo -u ailab uv run python scripts/backup_databases.py restore \
  --backup /var/backups/ai-inference-lab/<timestamp> \
  --label controller \
  --target /var/lib/ai-inference-lab/controller.sqlite3 \
  --replace
```

The helper snapshots the existing target as
`controller.sqlite3.pre-restore-<timestamp>.sqlite3` before replacement and runs
`PRAGMA integrity_check` on the restored copy. A failed restore leaves the
pre-restore snapshot in place. Repeat for `--label optimizer` and the optimizer
target. Then start services and verify `/ready`, worker snapshots and the
optimizer heartbeat.

## 10. Uninstall while retaining data

Remove the desktop package:

```bash
sudo apt-get remove ai-inference-lab-desktop
```

Stop and remove units if the backend is being retired:

```bash
sudo systemctl disable --now lab-worker.service lab-optimizer.service lab-controller.service
sudo rm /etc/systemd/system/lab-*.service
sudo systemctl daemon-reload
```

**Do not delete** `/var/lib/ai-inference-lab`, engine/model roots or backups
unless the operator explicitly requests permanent deletion. If permanent
deletion is requested, first confirm a verified off-host backup exists and then
delete only the named paths. Never delete a model root, engine installation or
unrelated GPU process as part of this project's uninstall.

## 11. Offline and live acceptance

Run the reproducible offline gates from the repository root:

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

These gates prove code, contracts, simulated recovery and local packaging. They
do not prove real engine performance, full-context allocation, GPU coexistence or
a live GUI session.

Live acceptance must be recorded separately with:

- host kernel, driver, CUDA, GPU UUID and total VRAM;
- engine ID/version/build/executable SHA-256;
- model ID, every shard SHA-256 and tokenizer hash;
- controller/optimizer commit and protocol version;
- exact contexts, workload digest and search depth;
- terminal state, any skipped context reason and confidence interval;
- confirmation that no unowned process was terminated.

Required live scenarios remain: full model hash scan, real preflight, one
low-impact tokenized trial, a near-capacity context check, a controller restart
during a trial with UI reconnect, a live Electron session, and the RTX 3060 /
L40S matrix. Until these are recorded, do not claim v1 acceptance.

## 12. Security checklist

- `/health` and `/ready` are the only public routes; all operator, worker and
  optimizer routes require the correct bearer kind.
- Disabled worker tokens cannot poll or heartbeat.
- The worker has no inbound listener; all commands are outbound polls.
- The desktop renderer has no Node integration, sandbox/context isolation are
  enabled, navigation and external URL opens are denied, and the token never
  enters the renderer.
- Release import is offline; no controller route downloads or installs an
  engine/model.
- Controller and optimizer databases are different files.
- No secret, model prompt, full environment dump or worker token is logged.
