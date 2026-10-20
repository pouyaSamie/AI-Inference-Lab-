# ADR 0011: the real worker owns processes, files and GPU leases

Status: accepted (Phase 2)

## Context

The Phase 1 contract deliberately kept adapters pure and made all execution
simulated. Real execution introduces privileges that must not leak into the
contract layer or the controller: spawning installed binaries, reading large
model files, accessing GPUs, terminating processes and retaining logs.

## Decision

- `lab_adapters` remains pure. It may only translate supplied facts and produce
  typed command plans (`CommandSpec`, `ServerExecutionPlan`).
- `lab_worker` is the only component that probes configured paths, reads model
  files, hashes artifacts, starts processes, binds a loopback server port,
  samples telemetry, acquires GPU leases and writes sandboxes/artifacts.
- The controller remains snapshot-only. It never probes an engine or starts a
  process; it queues durable commands and reconciles results.
- Every launched process is recorded in a mode-0600 journal with its process
  group and start ticks. Recovery kills only a recorded process group whose
  identity still matches; it never touches an unowned process.
- GPU access is serialized by per-UUID advisory `flock` files. The lease also
  scopes `CUDA_VISIBLE_DEVICES` and is held through renewal for long trials.
- Full-context preflight proves CPU allocation at the requested context. It
  explicitly does not infer GPU residency; that remains trial-measured.
- Missing evidence is left missing. Native-only trials are `screening_only`, and
  no real run can be marked simulated (or vice versa).

## Consequences

- The controller can be restarted without killing a worker or engine.
- A worker crash leaves the kernel to release GPU locks; the journal is the
  authority for owned process cleanup.
- Observability artifacts are local until Phase 4 uploads them through the
  durable completion/evidence path.
- Phase 2 cannot produce a validated recipe from an unserved native run; that
  remains a later-phase gate.
