# ADR 0015: Paired baselines, retained samples and qualification gates

Status: accepted (Phase 5)

## Context

Phase 1 could rank candidates by raw throughput, but that is not a defensible
winner: different candidates can run at different contexts, a single serving
summary hides variance, and there is no fixed control. The PRD requires paired
candidate/baseline comparisons, confidence handling and a pre-declared recipe
gate. Simulated and screening-only evidence must remain non-promotable.

The optimizer already writes objective scores through Optuna, and the worker
already repeats the primary serving level. Phase 5 needed to connect those
pieces without putting Optuna in FastAPI, inventing samples, or letting the
highest mean become a winner by default.

## Decision

1. **One fixed-default baseline per selected context.** The controller asks a
   baseline before normal TPE proposals. `AskPayload.baseline` makes the
   optimizer return the adapter's documented defaults. The baseline is persisted
   as a candidate with `role=baseline`.
2. **Baselines are controls, not search budget.** A study reserves one baseline
   slot per selected context. Those fixed controls do not consume the
   distinct-candidate search budget; normal TPE proposals remain capped by the
   declared policy.
3. **Retain primary repeats.** `BenchSample` records each completed
   primary-level repeat. The observation summary is still the median; samples
   are the paired evidence. Missing repeats are not synthesized.
4. **Optimize the objective ratio.** Candidate `tell` values are computed
   against the same-context baseline using the PRD objective formula. The
   baseline tells `1.0`.
5. **Finalization is recomputed from evidence.** `finalize_experiment` reads
   stored candidates and observations, selects the least-ineligible baseline
   and candidate observation, computes paired objective ratios, runs a seeded
   percentile bootstrap and applies the declared gate.
6. **No winner by default.** Qualification requires at least the declared
   improvement (default 5%) and a confidence interval strictly above `1.0`,
   with no guardrail failure. Missing samples, missing baseline, simulated or
   screening-only evidence, failed context proof or a failed quality gate make
   the candidate ineligible.
7. **Coverage is explicit.** Per-context winners are independent. Cross-context
   aggregation uses the geometric mean over exactly the selected contexts; a
   missing context makes the candidate ineligible for a global winner.
8. **Recipes re-check qualification.** Recipe creation returns `409` unless the
   candidate is measured, server-backed, baseline-paired, sample-complete and
   qualified. Accepted recipes are stored as `validated`; promotion stays
   separate.

## Consequences

- A candidate with higher raw throughput but high variance or a weak paired
  interval does not become a winner.
- Simulation exercises the control flow while remaining visibly `SIMULATED` and
  non-promotable.
- Results expose uncertainty, ineligibility reasons and incomplete coverage
  rather than silently choosing a screening leader.
- Baseline attempts add runtime overhead and are counted in study completion,
  but not against the distinct-candidate search cap.
- Full cross-context claims need every selected context; partial evidence stays
  visible but cannot produce a global winner.
- The path is verified offline only until a real paired baseline/candidate run
  is approved. No validated real recipe is claimed.

## Rejected alternatives

- **Compare all candidates to the global best mean.** Rejected: it is not a
  fixed control and ignores variance and context differences.
- **Use a single serving summary as if it were repeated evidence.** Rejected:
  the bootstrap needs paired repeats, and a summary hides dispersion.
- **Treat the first TPE sample as the baseline.** Rejected: it is not the
  engine's documented default and may be an arbitrarily bad control.
- **Let simulation produce a recipe because the mechanics pass.** Rejected:
  simulated evidence is not measured engine evidence.
- **Require only a point estimate above the threshold.** Rejected: the PRD gate
  requires confidence, not a lucky mean.
- **Average available contexts for a cross-context score.** Rejected: missing
  coverage must make the aggregate ineligible, not easier to win.
