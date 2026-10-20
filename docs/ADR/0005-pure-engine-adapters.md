# ADR 0005: Engine adapters are pure translators

Status: accepted (Phase 1)

## Context

Adapters need frequent changes as engine CLI help evolves. Embedding process,
filesystem or network behavior in them would make them hard to test, unsafe to
load and impossible to run in conformance fixtures.

## Decision

`python/lab_adapters` contains only pure Python: parse supplied help/version/
JSON, validate candidates, generate typed argv/`CommandSpec`/`ExecutionPlan`,
and parse already-captured evidence. No subprocess, socket, network, filesystem
or hardware probe. A static test rejects forbidden imports. The worker runner
will own all real I/O in Phase 2.

## Consequences

- Adapters are deterministic and testable from sanitized fixtures.
- Unknown flags must be rejected or explicitly version-mapped, never guessed.
- The future worker runner has a narrow, auditable trust boundary.
