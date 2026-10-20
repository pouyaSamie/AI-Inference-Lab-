# ADR 0008: SSE uses snapshots, per-experiment sequences and explicit gaps

Status: accepted (Phase 1)

## Context

Clients may disconnect, replay late, or fall behind retention. Reapplying a
non-contiguous event stream can corrupt UI state. The stream must not hold a DB
session or block the controller event loop.

## Decision

Every durable experiment event gets a monotonic per-experiment sequence.
Connections first receive a `snapshot` with current status and recent events,
then batched durable events with `id: <sequence>`. `Last-Event-ID` (or query)
selects replay. If the requested ID is below `replay_floors`, emit `event.gap`
then a fresh `snapshot`. `GET /events/page` provides bounded replay metadata
(`last_event_id`, `replay_floor`, `has_more`). SSE authentication is stateless,
and sessions are opened per poll/commit rather than held for the stream.

## Consequences

- Clients can detect lost history and recover without guessing.
- Event retention is a policy decision, not silent truncation.
- Sequence gaps are surfaced, never hidden.
