"""Statistical finalization and recipe qualification.

Finalization is deterministic and offline. It compares repeated measured
candidate samples with a paired baseline from the same experiment/context,
computes the PRD objective score, estimates a paired bootstrap interval and
applies the qualification gate. Simulated, screening-only and incomplete
evidence is retained for diagnosis but can never become a validated winner.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from pydantic import model_validator

from .base import FrozenModel, Identifier, NonNegativeInt
from .candidate import CandidateSpec
from .enums import (
    CandidateRole,
    ContextLength,
    EvidenceKind,
    MeasurementStatus,
    Objective,
    ObservationStatus,
    QualityGateStatus,
    RecipeMode,
)
from .experiment import ExperimentSpec
from .observation import BenchmarkObservation
from .scoring import (
    ConfidenceInterval,
    ScoreError,
    cross_context_score,
    objective_ratio,
    paired_ratio_ci,
    qualify_improvement,
    score_against_baseline,
)


class FinalizationStatus(StrEnum):
    VALIDATED = "validated"
    INCONCLUSIVE = "inconclusive"
    INELIGIBLE = "ineligible"


class Classification(StrEnum):
    VALIDATED_WINNER = "VALIDATED_WINNER"
    NO_VALIDATED_WINNER = "NO_VALIDATED_WINNER"
    SIMULATED = "SIMULATED"


class ContextEvaluation(FrozenModel):
    candidate_id: Identifier
    context: ContextLength
    baseline_candidate_id: Identifier | None = None
    baseline_observation_id: Identifier | None = None
    observation_id: Identifier | None = None
    score: float | None = None
    improvement_pct: float | None = None
    interval: ConfidenceInterval | None = None
    qualified: bool = False
    status: FinalizationStatus = FinalizationStatus.INELIGIBLE
    reasons: tuple[str, ...] = ()
    baseline_samples: NonNegativeInt = 0
    candidate_samples: NonNegativeInt = 0
    simulated: bool = False

    @model_validator(mode="after")
    def _qualified_requires_interval(self) -> ContextEvaluation:
        if self.qualified and (self.interval is None or self.score is None):
            raise ValueError("a qualified context requires a score and confidence interval")
        return self


class ContextRanking(FrozenModel):
    context: ContextLength
    baseline_candidate_id: Identifier | None = None
    winner_candidate_id: Identifier | None = None
    evaluations: tuple[ContextEvaluation, ...] = ()

    @model_validator(mode="after")
    def _winner_was_qualified(self) -> ContextRanking:
        if self.winner_candidate_id is not None:
            winner = next(
                (item for item in self.evaluations if item.candidate_id == self.winner_candidate_id),
                None,
            )
            if winner is None or not winner.qualified:
                raise ValueError("context winner must be a qualified evaluation")
        return self


class CrossContextRanking(FrozenModel):
    candidate_id: Identifier
    contexts: tuple[int, ...] = ()
    per_context_scores: tuple[float, ...] = ()
    score: float
    complete_coverage: bool
    qualified: bool
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _complete_requires_qualified_contexts(self) -> CrossContextRanking:
        if self.qualified and not self.complete_coverage:
            raise ValueError("cross-context qualification requires complete coverage")
        return self


class FinalizationResult(FrozenModel):
    experiment_id: Identifier
    objective: Objective
    recipe_mode: RecipeMode
    classification: Classification
    per_context: tuple[ContextRanking, ...] = ()
    cross_context: tuple[CrossContextRanking, ...] = ()
    validated_winner_candidate_id: Identifier | None = None
    simulated: bool = False
    warnings: tuple[str, ...] = ()
    threshold_pct: float = 5.0
    confidence_level: float = 0.95

    @model_validator(mode="after")
    def _winner_is_qualified(self) -> FinalizationResult:
        if self.validated_winner_candidate_id is not None:
            qualified_ids = {
                ranking.winner_candidate_id
                for ranking in self.per_context
                if ranking.winner_candidate_id is not None
            }
            qualified_ids.update(item.candidate_id for item in self.cross_context if item.qualified)
            if self.validated_winner_candidate_id not in qualified_ids:
                raise ValueError("validated winner must be a qualified context or cross-context winner")
        return self


def _gate(observation: BenchmarkObservation, name: str) -> QualityGateStatus | None:
    return next((gate.status for gate in observation.quality_gates if gate.name == name), None)


def _observation_reasons(
    observation: BenchmarkObservation,
    *,
    require_full_context_proof: bool,
) -> list[str]:
    reasons = list(observation.scoring_eligibility())
    if observation.evidence_kind is not EvidenceKind.SERVER_API:
        reasons.append("NON_SERVER_EVIDENCE")
    if (
        observation.metrics.prefill_tokens_per_sec is None
        or observation.metrics.decode_tokens_per_sec is None
    ):
        reasons.append("MISSING_COMPARABLE_THROUGHPUT")
    if observation.effective_context is not None and observation.effective_context < int(observation.context):
        reasons.append("EFFECTIVE_CONTEXT_BELOW_SELECTED")
    if require_full_context_proof:
        if _gate(observation, "context_truncation") is not QualityGateStatus.PASSED:
            reasons.append("FULL_CONTEXT_PROOF_MISSING")
        if _gate(observation, "planned_prompt_tokens") is not QualityGateStatus.PASSED:
            reasons.append("PLANNED_PROMPT_TOKENS_NOT_PROVEN")
    if len(observation.samples) < 2:
        reasons.append("INSUFFICIENT_PAIRED_SAMPLES")
    return list(dict.fromkeys(reasons))


def _observation_for(
    observations: Iterable[BenchmarkObservation],
    *,
    require_full_context_proof: bool,
) -> tuple[BenchmarkObservation | None, list[str]]:
    """Pick the least-ineligible observation deterministically."""
    candidates = list(observations)
    if not candidates:
        return None, ["NO_OBSERVATION"]
    evaluated = [
        (
            observation,
            _observation_reasons(
                observation,
                require_full_context_proof=require_full_context_proof,
            ),
        )
        for observation in candidates
    ]
    evaluated.sort(
        key=lambda item: (
            len(item[1]),
            -len(item[0].samples),
            item[0].observation_id,
        )
    )
    observation, reasons = evaluated[0]
    return observation, reasons


def _score_interval(
    objective: Objective,
    baseline: BenchmarkObservation,
    candidate: BenchmarkObservation,
    *,
    confidence_level: float,
) -> tuple[float | None, ConfidenceInterval | None, list[str]]:
    baseline_samples = baseline.samples
    candidate_samples = candidate.samples
    reasons: list[str] = []
    if len(baseline_samples) < 2 or len(candidate_samples) < 2:
        reasons.append("INSUFFICIENT_PAIRED_SAMPLES")
        point = None
        if (
            baseline.metrics.prefill_tokens_per_sec
            and baseline.metrics.decode_tokens_per_sec
            and candidate.metrics.prefill_tokens_per_sec
            and candidate.metrics.decode_tokens_per_sec
        ):
            point = objective_ratio(
                objective,
                baseline_prefill_tokens_per_sec=baseline.metrics.prefill_tokens_per_sec,
                baseline_decode_tokens_per_sec=baseline.metrics.decode_tokens_per_sec,
                candidate_prefill_tokens_per_sec=candidate.metrics.prefill_tokens_per_sec,
                candidate_decode_tokens_per_sec=candidate.metrics.decode_tokens_per_sec,
            )
        return point, None, reasons
    if len(baseline_samples) != len(candidate_samples):
        reasons.append("PAIRED_SAMPLE_COUNT_MISMATCH")
    count = min(len(baseline_samples), len(candidate_samples))
    ratios: list[float] = []
    for index in range(count):
        baseline_sample = baseline_samples[index]
        candidate_sample = candidate_samples[index]
        ratios.append(
            objective_ratio(
                objective,
                baseline_prefill_tokens_per_sec=baseline_sample.prefill_tokens_per_sec,
                baseline_decode_tokens_per_sec=baseline_sample.decode_tokens_per_sec,
                candidate_prefill_tokens_per_sec=candidate_sample.prefill_tokens_per_sec,
                candidate_decode_tokens_per_sec=candidate_sample.decode_tokens_per_sec,
            )
        )
    interval = paired_ratio_ci(ratios, confidence_level=confidence_level)
    return interval.point_estimate, interval, reasons


def _evaluate_candidate(
    *,
    candidate: CandidateSpec,
    baseline_candidate_id: str | None,
    baseline_observation: BenchmarkObservation | None,
    baseline_reasons: list[str],
    candidate_observations: Iterable[BenchmarkObservation],
    spec: ExperimentSpec,
    threshold_pct: float,
    confidence_level: float,
) -> ContextEvaluation:
    require_full = spec.constraints.require_full_context_proof
    observation, reasons = _observation_for(
        candidate_observations,
        require_full_context_proof=require_full,
    )
    simulated = bool(observation and observation.simulated)
    if baseline_candidate_id is None:
        reasons.append("NO_BASELINE_CANDIDATE")
    elif baseline_observation is None:
        reasons.extend(f"BASELINE_{reason}" for reason in baseline_reasons or ["UNAVAILABLE"])
    elif baseline_reasons:
        reasons.extend(f"BASELINE_{reason}" for reason in baseline_reasons)
    if observation is not None and observation.simulated:
        reasons.append("SIMULATED_EVIDENCE")
    if observation is not None and observation.status is not ObservationStatus.COMPLETED:
        reasons.append(f"STATUS_{observation.status.value.upper()}")
    if observation is not None and observation.measurement_status is not MeasurementStatus.MEASURED:
        reasons.append(f"MEASUREMENT_{observation.measurement_status.value.upper()}")
    reasons = list(dict.fromkeys(reasons))

    score: float | None = None
    interval: ConfidenceInterval | None = None
    if baseline_observation is not None and observation is not None and not baseline_reasons:
        score, interval, score_reasons = _score_interval(
            spec.objective,
            baseline_observation,
            observation,
            confidence_level=confidence_level,
        )
        reasons.extend(score_reasons)
        reasons = list(dict.fromkeys(reasons))
        # Cross-check the point score with the PRD's ratio formula on the
        # summarized metrics. This catches an inconsistent sample set.
        if (
            score is not None
            and baseline_observation.metrics.prefill_tokens_per_sec
            and baseline_observation.metrics.decode_tokens_per_sec
            and observation.metrics.prefill_tokens_per_sec
            and observation.metrics.decode_tokens_per_sec
        ):
            try:
                score_against_baseline(
                    spec.objective,
                    baseline_prefill_tokens_per_sec=baseline_observation.metrics.prefill_tokens_per_sec,
                    baseline_decode_tokens_per_sec=baseline_observation.metrics.decode_tokens_per_sec,
                    candidate_prefill_tokens_per_sec=observation.metrics.prefill_tokens_per_sec,
                    candidate_decode_tokens_per_sec=observation.metrics.decode_tokens_per_sec,
                )
            except ScoreError:
                reasons.append("INVALID_SCORE_COMPONENTS")
                score = None
                interval = None

    qualified = False
    improvement_pct: float | None = None
    if score is not None and interval is not None:
        decision = qualify_improvement(
            score=score,
            interval_lower=interval.lower,
            min_improvement_pct=threshold_pct,
            confidence_level=confidence_level,
            guardrails_passed=not reasons,
        )
        qualified = decision.qualified
        improvement_pct = decision.improvement_pct
        reasons.extend(decision.reasons)
        reasons = list(dict.fromkeys(reasons))
    elif score is not None:
        improvement_pct = (score - 1.0) * 100.0

    hard = bool(
        set(reasons)
        & {
            "SIMULATED_EVIDENCE",
            "NO_OBSERVATION",
            "NO_BASELINE_CANDIDATE",
            "NON_SERVER_EVIDENCE",
            "MISSING_COMPARABLE_THROUGHPUT",
            "FULL_CONTEXT_PROOF_MISSING",
            "PLANNED_PROMPT_TOKENS_NOT_PROVEN",
            "INSUFFICIENT_PAIRED_SAMPLES",
            "INVALID_SCORE_COMPONENTS",
        }
    ) or any(reason.startswith("BASELINE_") for reason in reasons)
    status = (
        FinalizationStatus.VALIDATED
        if qualified
        else (FinalizationStatus.INELIGIBLE if hard else FinalizationStatus.INCONCLUSIVE)
    )
    return ContextEvaluation(
        candidate_id=candidate.candidate_id,
        context=candidate.context,
        baseline_candidate_id=baseline_candidate_id,
        baseline_observation_id=baseline_observation.observation_id if baseline_observation else None,
        observation_id=observation.observation_id if observation else None,
        score=score,
        improvement_pct=improvement_pct,
        interval=interval,
        qualified=qualified,
        status=status,
        reasons=tuple(reasons),
        baseline_samples=len(baseline_observation.samples) if baseline_observation else 0,
        candidate_samples=len(observation.samples) if observation else 0,
        simulated=simulated
        or bool(observation and observation.measurement_status is MeasurementStatus.SIMULATED),
    )


def finalize_experiment(
    *,
    experiment_id: str,
    spec: ExperimentSpec,
    candidates: Iterable[CandidateSpec],
    observations: Iterable[BenchmarkObservation],
) -> FinalizationResult:
    """Recompute per-context and cross-context winners from stored evidence."""
    candidate_list = list(candidates)
    observation_list = list(observations)
    by_candidate: dict[str, list[BenchmarkObservation]] = {}
    for observation in observation_list:
        by_candidate.setdefault(observation.candidate_id, []).append(observation)

    baselines_by_context: dict[int, list[CandidateSpec]] = {}
    for candidate in candidate_list:
        if candidate.role is CandidateRole.BASELINE:
            baselines_by_context.setdefault(int(candidate.context), []).append(candidate)

    threshold = spec.search_policy.min_improvement_pct
    confidence = spec.search_policy.confidence_level
    per_context: list[ContextRanking] = []
    evaluations_by_candidate: dict[str, list[ContextEvaluation]] = {}

    for context in spec.contexts:
        baseline_candidates = sorted(
            baselines_by_context.get(int(context), []),
            key=lambda item: item.candidate_id,
        )
        baseline_candidate = baseline_candidates[0] if baseline_candidates else None
        baseline_observation: BenchmarkObservation | None = None
        baseline_reasons: list[str] = []
        if baseline_candidate is not None:
            baseline_observation, baseline_reasons = _observation_for(
                by_candidate.get(baseline_candidate.candidate_id, ()),
                require_full_context_proof=spec.constraints.require_full_context_proof,
            )
        evaluations: list[ContextEvaluation] = []
        for candidate in candidate_list:
            if candidate.role is CandidateRole.BASELINE or int(candidate.context) != int(context):
                continue
            evaluation = _evaluate_candidate(
                candidate=candidate,
                baseline_candidate_id=baseline_candidate.candidate_id if baseline_candidate else None,
                baseline_observation=baseline_observation,
                baseline_reasons=baseline_reasons,
                candidate_observations=by_candidate.get(candidate.candidate_id, ()),
                spec=spec,
                threshold_pct=threshold,
                confidence_level=confidence,
            )
            evaluations.append(evaluation)
            evaluations_by_candidate.setdefault(candidate.candidate_id, []).append(evaluation)
        evaluations.sort(
            key=lambda item: (
                not item.qualified,
                -(item.score or 0.0),
                item.candidate_id,
            )
        )
        winner = next((item.candidate_id for item in evaluations if item.qualified), None)
        per_context.append(
            ContextRanking(
                context=context,
                baseline_candidate_id=baseline_candidate.candidate_id if baseline_candidate else None,
                winner_candidate_id=winner,
                evaluations=tuple(evaluations),
            )
        )

    cross_context: list[CrossContextRanking] = []
    for candidate in candidate_list:
        if candidate.role is CandidateRole.BASELINE:
            continue
        evaluations = evaluations_by_candidate.get(candidate.candidate_id, [])
        scores = {int(item.context): item.score for item in evaluations if item.score is not None}
        aggregate = cross_context_score(
            spec.objective,
            scores_by_context=scores,
            selected_contexts=[int(context) for context in spec.contexts],
        )
        context_qualified = {int(item.context): item.qualified for item in evaluations}
        complete = aggregate.complete_coverage
        all_qualified = complete and all(
            context_qualified.get(int(context), False) for context in spec.contexts
        )
        reasons: list[str] = []
        if not complete:
            reasons.append("INCOMPLETE_CONTEXT_COVERAGE")
        if complete and not all_qualified:
            reasons.append("CONTEXT_NOT_QUALIFIED")
        cross_context.append(
            CrossContextRanking(
                candidate_id=candidate.candidate_id,
                contexts=aggregate.contexts,
                per_context_scores=aggregate.per_context_scores,
                score=aggregate.score,
                complete_coverage=complete,
                qualified=all_qualified,
                reasons=tuple(reasons),
            )
        )
    cross_context.sort(key=lambda item: (not item.qualified, -item.score, item.candidate_id))

    simulated = any(observation.simulated for observation in observation_list) or any(
        observation.measurement_status is MeasurementStatus.SIMULATED for observation in observation_list
    )
    context_winners = [item.winner_candidate_id for item in per_context if item.winner_candidate_id]
    cross_winner = (
        cross_context[0].candidate_id
        if spec.recipe_mode is RecipeMode.CROSS_CONTEXT and cross_context and cross_context[0].qualified
        else None
    )
    if cross_winner is not None:
        validated_winner = cross_winner
    elif spec.recipe_mode is RecipeMode.PER_CONTEXT and len(spec.contexts) == 1 and context_winners:
        validated_winner = context_winners[0]
    else:
        validated_winner = None

    warnings: list[str] = []
    if simulated:
        warnings.append("SIMULATED_RESULTS_NOT_VALIDATED_FOR_DEPLOYMENT")
    if not any(item.baseline_candidate_id for item in per_context):
        warnings.append("NO_BASELINE_EVIDENCE")
    if not context_winners and not cross_winner:
        warnings.append("NO_VALIDATED_WINNER")
    if any(not item.complete_coverage for item in cross_context):
        warnings.append("INCOMPLETE_CROSS_CONTEXT_COVERAGE")
    if any(
        gate.status is QualityGateStatus.FAILED
        for observation in observation_list
        for gate in observation.quality_gates
    ):
        warnings.append("QUALITY_GATE_REGRESSION_PRESENT")

    classification = (
        Classification.SIMULATED
        if simulated
        else (
            Classification.VALIDATED_WINNER
            if context_winners or cross_winner
            else Classification.NO_VALIDATED_WINNER
        )
    )
    return FinalizationResult(
        experiment_id=experiment_id,
        objective=spec.objective,
        recipe_mode=spec.recipe_mode,
        classification=classification,
        per_context=tuple(per_context),
        cross_context=tuple(cross_context),
        validated_winner_candidate_id=validated_winner,
        simulated=simulated,
        warnings=tuple(dict.fromkeys(warnings)),
        threshold_pct=threshold,
        confidence_level=confidence,
    )
