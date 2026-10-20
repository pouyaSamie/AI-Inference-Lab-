# Phase 2 report — real Linux worker

Date: 2026-10-21

Status: **implemented and verified at the worker/protocol boundary; real
preflight and trial evidence remain unproven.**

This report records only work actually performed. It does not convert probe
results into benchmark evidence.

## 1. Delivered

### Worker discovery

- `lab_worker/hardware.py` — host CPU/RAM and NVIDIA GPU discovery, external
  process detection, bounded telemetry sampling (`nvidia-smi`, `psutil`).
- `lab_worker/engines.py` — probes only configured binaries, hashes every
  executable, parses llama.cpp/Strata `--version`/`--help` through the pure
  adapters, and builds trusted binary registries.
- `lab_worker/models.py` — GGUF header/shard parsing, Strata pack discovery,
  `(size, mtime_ns)` SHA-256 cache, read-only traversal. Files are marked
  verified only when strong hashes were actually computed.
- `lab_worker/discovery.py` — revisioned inventory snapshots with warnings.

### Execution and recovery

- `lab_worker/runner.py` — argv-only process runner with verified executable
  hash, sanitized environment, process-group ownership, readiness checks,
  bounded output capture, telemetry ticks, timeout/cancel escalation and a
  loopback server starter.
- `lab_worker/gpu.py` — UUID-addressed advisory `flock` leases plus owner JSON;
  sorted multi-GPU acquisition; stale-record reconciliation.
- `lab_worker/journal.py` — append-only 0600 journal, process start-tick
  identity, owned-group recovery and interrupted output tails.
- `lab_worker/sandbox.py` — per-command sandbox directories and bounded cleanup.
- `lab_worker/bench.py` — OpenAI-compatible streaming workload, TTFT/latency,
  effective-context read, cancellation and telemetry.
- `lab_worker/real_executor.py` — `SCAN`, `PREFLIGHT`, `CLAIM_TRIAL`, `PAUSE`,
  `CANCEL`, `VERIFY_RECIPE`, dry-run `PROMOTE`.
- `lab_worker/real_worker.py` — real polling/heartbeat loop, inventory sync,
  journal recovery, lease renewal and graceful shutdown.
- `python/lab_worker/lab_worker/main.py` — `lab-worker` is now the real lane and
  `lab-worker-sim` is the explicit simulation lane.

### Controller/protocol

- `POST /api/v1/workers/{id}/commands/{cid}/renew` plus service-level lease
  renewal with token/generation checks and a configured maximum expiry.
- `LAB_EXECUTION_MODE=real` accepted; startup still validates separate stores
  and credentials.
- `ServerExecutionPlan.generated_files` carries generated profile identity, and
  plans include it in their digest.
- `HashCache.flush` serialization fixed; Strata artifacts without hashes no
  longer claim `verified=true`.

### Packaging and documentation

- `packaging/systemd/lab-controller.service`
- `packaging/systemd/lab-optimizer.service`
- `packaging/systemd/lab-worker.service`
- `packaging/systemd/lab.env.example`
- `packaging/systemd/README.md` (installation outline marked **not executed**)
- ADR 0011 (worker owns processes/files/GPU leases)
- ADR 0012 (renewable leases and observed identity)
- Architecture, README, AGENTS, `.env.example` updated for Phase 2.

## 2. Safety boundaries

- The real worker never writes under a model or engine root, never downloads or
  replaces a binary, and never terminates an unowned process.
- The worker has no inbound listener; every controller connection is outbound.
- Adapters remain pure. A test rejects `subprocess`, network, `pathlib`, `os`
  and hardware imports in `lab_adapters`.
- The simulated lane cannot emit `simulated=false`. Real preflight/trials reject
  incomplete model hashes.
- Plan execution verifies the observed engine SHA-256 before spawning.
- GPU leases use `flock`, so a crashed worker cannot leave a lock that blocks the
  host forever; the kernel releases it.
- Full-context preflight is explicitly a CPU-offload allocation proof, not a
  claim of GPU residency.

## 3. Commands actually run

### Static gates (final run in this tree)

```bash
uv run ruff check
# All checks passed!

uv run ruff format --check
# 105 files already formatted

uv run mypy python
# Success: no issues found in 90 source files

uv run pytest -q
# 25 passed in 7.91s

uv run python scripts/check_contracts.py
# contracts are current

pnpm typecheck
# tsc --noEmit -p tsconfig.json: passed
```

`systemd-analyze verify packaging/systemd/lab-controller.service
packaging/systemd/lab-optimizer.service packaging/systemd/lab-worker.service`
parsed the units and reported only missing deployment executables:

```text
lab-controller.service: Command /opt/ai-inference-lab/.venv/bin/lab-api is not executable
lab-optimizer.service: Command /opt/ai-inference-lab/.venv/bin/lab-optimizer is not executable
lab-worker.service: Command /opt/ai-inference-lab/.venv/bin/lab-worker is not executable
```

No unit was installed, enabled or started.

### Live engine/model discovery

```bash
uv run python -  # WorkerSettings + discover_engines + discover_models, hashing disabled
```

Observed:

```text
ENGINE llamacpp 0.7.0-dev build 701 commit dd002b91f sha256 f0f8a33ee87c...
ENGINE strata   0.1.44.1  build 0.1.44.1 sha256 fa29349e3eaa...
MODELS 8
```

The 8 artifacts were 6 GGUF models and 2 Strata packs. All were reported
`verified=false` because this probe deliberately disabled hashing. No model or
engine file was modified.

### Live controller/worker protocol smoke

- Temporary controller: loopback `127.0.0.1:8790`, `LAB_EXECUTION_MODE=real`,
  controller/optimizer SQLite files under `/tmp/opencode/lab-phase2`.
- Alembic upgraded the temporary controller database successfully.
- Real worker `real-smoke-1` used a separate state root and model root.
- `lab-worker --scan-only` registered, uploaded a hardware/engine/model
  snapshot and heartbeat.
- A queued durable `SCAN` command (`cmd_3e8f46b022ff472a9d6a7c8ea97b7772`) was
  polled, acked and completed in about 1.5 s with hashing disabled.
- Controller command status became `completed`; snapshot revision 5 was
  accepted.

This is a protocol and discovery smoke only. It is not a benchmark.

## 4. Not performed

- Full SHA-256 scan of the ~270 GiB model root.
- Real `PREFLIGHT` at 4K/32K/128K.
- Real `CLAIM_TRIAL` or measured TTFT/throughput/VRAM/quality.
- Strata serving calibration or full-context proof.
- Second-GPU comparison (only the RTX 3060 is installed).
- Systemd installation, enablement or production deployment.
- Destructive or privileged host changes.

## 5. Known limitations

- `PAUSE` stops the active trial at the process group; resumable checkpoints are
  not implemented.
- The initial full hash scan is expensive; the cache makes repeat scans cheap.
- Strata preflight is `INCONCLUSIVE` until Phase 4, because the installed build
  exposes no calibration command.
- The worker selects the snapshot's GPU unless a command supplies UUIDs; CPU-only
  llama candidates skip GPU leasing.
- No real artifact upload path is exercised yet; evidence is referenced by
  local sanitized log paths and typed observations.

## 6. Exit criteria met

- [x] Real worker entry point with observed discovery and heartbeat.
- [x] Durable poll/ack/renew/complete path exercised live.
- [x] Argv-only runner with timeout/cancel/process-group tests.
- [x] GPU UUID lease exclusivity test.
- [x] Journal crash-recovery test.
- [x] Read-only model discovery with GGUF/shard tests.
- [x] Pure-adapter boundary preserved.
- [x] Contracts current; no generated-file drift.
- [x] Systemd units authored and syntax-checked, not installed.

## 7. Next

Phase 3 productionizes the llama.cpp and Strata adapters and adds conformance
coverage against the installed builds. Before any real recipe can be considered,
run a full hash scan, one real preflight and one low-impact real trial under
operator approval. See `docs/NEXT_STEPS.md`.
