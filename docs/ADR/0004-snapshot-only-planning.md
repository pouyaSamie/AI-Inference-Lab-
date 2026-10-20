# ADR 0004: Experiment planning consumes cached snapshots only

Status: accepted (Phase 1)

## Context

A plan endpoint that probes a worker synchronously would couple UI latency to
GPU availability, violate the controller's event-loop discipline and risk
building plans from half-live state.

## Decision

`POST /api/v1/experiments/plan` reads the latest persisted worker snapshot. If
the heartbeat, snapshot age or revision is not fresh, it returns HTTP `202` with
`status=preflight_required`, a typed reason and a queued `SCAN` command ID.
Otherwise it returns an immutable `ExperimentPlan` and adapter-derived search
space. No live RPC or binary/model read occurs in the route.

## Consequences

- Planning is fast, deterministic and offline-testable.
- Operators may need a second request after inventory refresh.
- Staleness policy is explicit configuration, not a hidden retry.
