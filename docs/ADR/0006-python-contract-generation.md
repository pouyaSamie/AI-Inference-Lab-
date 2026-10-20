# ADR 0006: Dependency-free deterministic contract generation

Status: accepted (Phase 1; revisit if the generator becomes a maintenance burden)

## Context

PRD v2.1 proposes `pnpm generate:contracts` using `@hey-api/openapi-ts` or
`openapi-typescript`, with CI drift detection. Those generators require a Node
dependency and potentially network installation, while this phase must generate
and verify contracts fully offline, without starting an HTTP listener.

## Decision

Three small Python scripts generate the committed artifacts:

- `scripts/export_openapi.py` builds `app.openapi()` in-process;
- `scripts/export_schemas.py` exports selected frozen Pydantic protocol schemas
  and a SHA-256 manifest;
- `scripts/export_ts.py` transforms the committed OpenAPI document into strict
  TypeScript declarations.

`scripts/check_contracts.py` regenerates in memory and fails on drift. Output is
JSON with sorted keys and deterministic property ordering. `pnpm
generate:contracts` invokes the scripts. TypeScript is checked with `tsc
--noEmit` (`pnpm typecheck`).

## Consequences

- Generation and CI checks work with no network and no schema server.
- We own a small generator; it must be extended if OpenAPI features require it.
- The generated files remain disposable and must not be hand-edited.
