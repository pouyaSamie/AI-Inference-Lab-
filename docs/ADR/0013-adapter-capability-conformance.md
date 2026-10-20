# ADR 0013 — Adapter capability conformance for installed builds

Date: 2026-10-21
Status: accepted

## Context

Phase 2 proved that the worker can observe binaries and execute argv-only
plans, but the adapters were still permissive in places:

- capability extraction scanned all help text, so a flag mentioned only in prose
  could be treated as an observed option;
- llama.cpp server and `llama-bench` output were merged before checking required
  flags;
- candidate validation rejected non-integer values for integer flags but did not
  consistently reject booleans-as-integers, non-finite floats, wrong booleans or
  numeric strings;
- the Strata adapter treated `--expert-cache` as a string, used a non-zero
  default for `--pool-workers`, and could duplicate flags already present in
  operator base args;
- `native: true` in Strata model metadata is a discovery marker, not a shard
  path, but stringifying it produced the invalid argument `--native True`;
- the installed Strata build does not expose `--mtp` as an option definition,
  even though its help prose mentions it.

The installed builds are authoritative. A newer upstream manual must not turn an
unobserved flag into a runnable capability.

## Decision

1. `observed_flags` and `flag_aliases` consider only help lines that begin an
   option. Prose mentions are not capabilities.
2. The llama.cpp adapter parses server and `llama-bench` help separately and
   requires each lane's mandatory flags before accepting the combined manifest.
   It records both help digests in the manifest notes.
3. A shared `validate_capability_value` helper enforces strict types and bounds
   for enum, integer, float, boolean and string descriptors. Candidate values
   that fail are never translated into argv.
4. The Strata adapter models the installed `0.1.44.1` surface:
   `--expert-cache` is integer default `0`, `--pool-workers=0` means all physical
   cores, `--kv-resident` is `0` or at least `20480`, and `--batch` is opt-in.
5. Strata profile generation removes all adapter-managed flags from operator
   base args before re-emitting typed values. The `native: true` marker is not a
   path; only an explicit `native_shard` emits `--native SHARD1`. The unobserved
   `--mtp` form is not emitted.
6. Missing source-shard resolution is recorded as a boundary, not guessed. The
   Strata pack remains usable without `--native`; full-context proof remains
   `INCONCLUSIVE` until the Phase 4 serving harness.
7. Offline golden fixtures cover installed help/version, `llama-bench` JSON,
   `/props`, and Strata `/v1/status`. The worker passes `/props` or `/v1/status`
   through the adapter for context identity, but client-observed throughput and
   peak telemetry keep precedence.

## Consequences

- A help-prose mention can no longer create a capability.
- A build missing required server or bench flags fails discovery rather than
  producing a plan that would fail after spawning.
- Invalid candidate types fail before execution.
- Strata profiles no longer contain duplicate managed flags or a boolean
  stringified into `--native`.
- `--mtp` and other unobserved options remain unavailable. If a future installed
  build exposes them, a new fixture and conformance test must be added first.
- Full-context Strata evidence still cannot be claimed until Phase 4 and real
  operator-approved measurements.
