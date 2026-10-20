# ADR 0012: renewable command leases and observed identity

Status: accepted (Phase 2)

## Context

Real model loading and benchmarking can exceed the initial command lease. A
worker must keep ownership without allowing a duplicate worker to execute the
same command. At the same time, an engine or model changing underneath a plan
must fail closed rather than produce evidence for the wrong artifact.

## Decision

- Poll issues a random lease token and a monotonic generation. Only a hashed
  token is persisted.
- `POST .../renew` requires the same worker, token and generation. It extends
  expiry up to the controller's configured maximum. It never changes the
  generation and never allows a different worker to take over a live lease.
- The worker renews on a wall-clock interval while starting a server, running a
  benchmark or streaming a completion. Renewal failures are logged; they do not
  fabricate a successful measurement.
- Command plans carry the observed engine executable SHA-256 and model artifact
  digest. The worker verifies the installed engine digest against its trusted
  registry before spawning. A mismatch fails closed and asks for a fresh scan.
- Model discovery hashes files with a persistent `(size, mtime_ns)` cache. A
  snapshot with incomplete hashes is allowed for planning but is flagged; the
  worker never claims an unhashed file is verified.

## Consequences

- Long trials keep a valid lease without weakening generation checks.
- A worker cannot resume another worker's command simply because a lease
  expired; a live process remains owned by its journal.
- Engine upgrades or weight changes invalidate planned identities instead of
  contaminating evidence.
