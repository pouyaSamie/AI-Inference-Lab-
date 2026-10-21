# ADR 0017 — Offline release intelligence and non-approving A/B records

- Status: accepted
- Date: 2026-10-21
- Phase: 7

## Context

The PRD requires source/build-aware update notices, deterministic impact
classification, pin/defer decisions and a controlled paired old/new comparison.
It also requires that detecting an update never changes the installed engine or
model, and that no remote egress or artifact download happens by default.

The installed llama.cpp and Strata builds cannot be replaced or probed for an
uninstalled candidate. A release check therefore cannot observe the candidate
binary itself; it can only assess imported release metadata against cached
worker inventory.

## Decision

1. **Offline import is the only implemented source.**
   `POST /api/v1/releases/check` accepts a `ReleaseMetadata` document. It makes
   no HTTP request, starts no process, hashes no new artifact and writes nothing
   outside the controller database. `github_release` is a metadata source label,
   not an implemented remote fetcher. Remote polling remains future opt-in work.

2. **Classification is deterministic and conservative.**
   Pure `lab_updates` code maps changed repository paths and explicit changed
   areas to P0/P1/P2. CUDA/backend/MoE/KV/context/model-loader areas are P0;
   scheduling/threading/batching/server API are P1; docs/tests/unrelated GPU
   architecture are P2. Unknown paths are P1 and force a smoke test. A
   capability-schema diff can raise impact but never lowers it. Stale inventory
   can raise a P2 result to P1; missing current-engine identity makes the release
   non-applicable rather than silently compatible.

3. **Notices and assessments are durable and replay-safe.**
   A notice ID is derived from the canonical metadata digest. A repeated import
   returns the existing notice. An assessment ID binds notice, worker, model
   digest, current executable hash, inventory revision and policy version.
   Reassessing the same facts is idempotent; a changed worker/model/inventory
   creates a new assessment without overwriting prior evidence.

4. **A/B proposals are frozen records, not executions.**
   Comparison creation requires an applicable P0/P1 assessment, a complete
   verified model identity digest, the candidate executable SHA-256 and the
   selected worker. It freezes both engine identities, workload suite, contexts
   and thresholds. No engine is
   started, no binary is installed and no evidence is fabricated. Evidence is
   submitted separately through an operator-authenticated endpoint after a
   measured run.

5. **Qualification never approves an upgrade.**
   Results are `IMPROVED`, `REGRESSED`, `INCONCLUSIVE` or `INCOMPATIBLE`.
   `upgrade_approved` is a literal `False`; even `IMPROVED` only recommends
   operator review. Simulated evidence, non-measured status, identity mismatch,
   missing contexts, baseline guardrail failure or a missing candidate sample
   makes the result incompatible or ineligible. A candidate guardrail failure or
   a statistically significant regression retains the current engine.

6. **Evidence submission is immutable and replay-safe.**
   Repeating identical terminal evidence returns the stored result. Submitting
   different evidence for a terminal comparison returns `409`; a new proposal is
   required. This prevents result shopping and silent evidence replacement.

7. **The desktop page is a read-only review surface plus explicit controls.**
   It can import offline JSON, pin/defer notices and request an A/B proposal. It
   cannot download, install, launch or approve an engine. It labels the lack of
   upstream egress and the non-approving nature of every comparison.

## Consequences

- The release workflow works without network access, credentials or candidate
  binaries, and its decisions can be audited and replayed.
- A candidate executable hash is mandatory for a safe comparison. Metadata
  without it can be assessed but cannot become an A/B study.
- A real A/B run still requires a separately implemented, operator-approved
  execution path and real measured samples. This phase does not claim one.
- Remote release polling, artifact download and installation remain outside
  this decision and require their own security review and explicit approval.
- The UI and API cannot turn a release notice into a recipe, promotion or
  installed binary.
