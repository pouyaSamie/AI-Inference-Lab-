# ADR 0007: Phase 1 execution is explicitly simulated

Status: accepted (Phase 1); the simulated lane remains binding. The statement that `execution_mode=real` is rejected was superseded by ADR 0011 in Phase 2.

## Context

The Phase 1 gate is protocol, persistence, planning and recovery; it must be
testable on any machine without a GPU, model download or live engine. Mixing
simulated observations with real evidence would be scientifically unsafe.

## Decision

`lab-worker-sim` runs a deterministic simulated executor. Every observation is
marked `simulated=true` and `measurement_status=simulated`; inventory says no
live probe occurred. `create_app()` rejects `execution_mode=real` with a clear
error. Recipe creation rejects simulated evidence with HTTP `409`. `lab-worker`
logs a warning and forwards to the simulated lane.

## Consequences

- Phase 1 tests are portable and fast.
- The system cannot produce a validated recipe until real evidence exists.
- Phase 2 adds a real runner without changing the durable command contract.
