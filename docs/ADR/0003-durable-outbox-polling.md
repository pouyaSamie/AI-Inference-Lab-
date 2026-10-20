# ADR 0003: Durable controller outbox and outbound worker polling

Status: accepted (Phase 1)

## Context

Workers may sit behind NAT/firewalls, and the controller must not depend on a
desktop session or an inbound worker port. A lost HTTP response must not cause a
command to be silently dropped or executed twice.

## Decision

The controller stores commands in `worker_commands`. Workers poll outbound over
authenticated HTTP, receive leases with opaque tokens and generations, ack, then
complete with a typed, idempotency-keyed result. Terminal completions are
replay-safe: the same result returns `idempotent_replay=true`; a conflicting
result returns `409`. Expired leases are requeued with a new generation/token.

## Consequences

- No inbound worker listener is required.
- Polling adds latency; acceptable for Phase 1 foundation.
- Lease expiry alone cannot prove a process is dead; real process ownership and
  reconciliation remain a Phase 2 worker responsibility.
