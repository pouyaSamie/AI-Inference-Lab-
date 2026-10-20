# systemd units (authoring only)

These three units are provided for review and packaging. **They have not been
installed or enabled on this host.** Installation is a privileged system change
and requires explicit operator approval.

## Layout

| Unit | Process | Required access |
|---|---|---|
| `lab-controller.service` | `lab-api` | controller SQLite, artifacts, loopback port |
| `lab-optimizer.service` | `lab-optimizer` | separate Optuna SQLite, loopback controller |
| `lab-worker.service` | `lab-worker` | GPU devices, model roots read-only, worker state |

The controller and optimizer deliberately use separate SQLite files. The worker
uses the outbound polling protocol and never exposes an inbound port.

## Installation outline (not executed)

1. Create a dedicated `ailab` user and a read-only checkout/deployment at
   `/opt/ai-inference-lab`; run `uv sync --all-packages` there.
2. Install `lab.env.example` as `/etc/ai-inference-lab/lab.env`, replace every
   `CHANGE_ME`, and set mode `0640 root:ailab`.
3. Review the `DeviceAllow` entries for the host's NVIDIA device numbers.
4. Approve and then install the units:

   ```bash
   sudo install -d /etc/ai-inference-lab
   sudo install -m 0640 -o root -g ailab packaging/systemd/lab.env.example /etc/ai-inference-lab/lab.env
   sudo install -m 0644 packaging/systemd/lab-*.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now lab-controller.service
   sudo systemctl enable --now lab-optimizer.service
   sudo systemctl enable --now lab-worker.service
   ```

5. Enroll the worker once with a scoped enrollment credential. Store the
   returned worker token in a root-only secret file or credential unit; do not
   put it in the unit file.

## Security notes

- No unit runs as root. The worker must be able to read model files and access
  the NVIDIA devices, but it never writes to model or engine directories.
- `ProtectHome=read-only` keeps `/home` readable for model roots while denying
  writes. Adjust the unit if models live under a different read-only mount.
- The worker's journal, sandbox, artifacts and hash cache live under
  `/var/lib/ai-inference-lab/worker` (or `LAB_WORKER_STATE_ROOT`).
- The worker terminates only process groups it recorded in its journal. It does
  not kill unrelated GPU processes.
- The optimizer and controller units share no database.
