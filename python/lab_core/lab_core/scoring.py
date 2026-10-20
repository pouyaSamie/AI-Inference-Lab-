"""Objective scoring contracts and deterministic statistical helpers.

Phase 1 implements the scoring contract and its invariants. Phase 5 adds the
full optimizer integration, feasibility-aware pruners and finalist selection.
Failed/OOM candidates are never represented as a zero-throughput value here.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence

from pydantic import model_validator

from .base import FrozenModel, NonEmptyStr, Probability
from .enums import Objective


class ScoreError(ValueError):
    """Raised when a score is requested from invalid or incomparable inputs."""


class ScoreComponents(FrozenModel):
    prefill_ratio: float
    decode_ratio: float
    baseline_prefill_tokens_per_sec: float
    baseline_decode_tokens_per_sec: float
    candidate_prefill_tokens_per_sec: float
    candidate_decode_tokens_per_sec: float

    @model_validator(mode="after")
    def _positive(self) -> ScoreComponents:
        values = (
            self.prefill_ratio,
            self.decode_ratio,
            self.baseline_prefill_tokens_per_sec,
            self.baseline_decode_tokens_per_sec,
            self.candidate_prefill_tokens_per_sec,
            self.candidate_decode_tokens_per_sec,
        )
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("score components require finite, positive throughput values")
        return self


class ObjectiveScore(FrozenModel):
    objective: Objective
    score: float
    components: ScoreComponents

    @model_validator(mode="after")
    def _finite(self) -> ObjectiveScore:
        if not math.isfinite(self.score) or self.score <= 0:
            raise ValueError("objective score must be finite and positive")
        return self


def score_against_baseline(
    objective: Objective,
    *,
    baseline_prefill_tokens_per_sec: float,
    baseline_decode_tokens_per_sec: float,
    candidate_prefill_tokens_per_sec: float,
    candidate_decode_tokens_per_sec: float,
) -> ObjectiveScore:
    """Compute the versioned objective score exactly as specified in the PRD.

    Balanced uses ``sqrt(PPx/PP0 * TGx/TG0)``; decode and prefill use their
    respective ratios. All inputs must be measured, valid and positive.
    """
    for name, value in (
        ("baseline_prefill_tokens_per_sec", baseline_prefill_tokens_per_sec),
        ("baseline_decode_tokens_per_sec", baseline_decode_tokens_per_sec),
        ("candidate_prefill_tokens_per_sec", candidate_prefill_tokens_per_sec),
        ("candidate_decode_tokens_per_sec", candidate_decode_tokens_per_sec),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ScoreError(f"{name} must be a finite positive measurement, got {value!r}")
    prefill_ratio = candidate_prefill_tokens_per_sec / baseline_prefill_tokens_per_sec
    decode_ratio = candidate_decode_tokens_per_sec / baseline_decode_tokens_per_sec
    if objective is Objective.BALANCED:
        value = math.sqrt(prefill_ratio * decode_ratio)
    elif objective is Objective.DECODE_MAX:
        value = decode_ratio
    elif objective is Objective.PREFILL_MAX:
        value = prefill_ratio
    else:  # pragma: no cover - exhaustive enum
        raise ScoreError(f"unsupported objective: {objective!r}")
    components = ScoreComponents(
        prefill_ratio=prefill_ratio,
        decode_ratio=decode_ratio,
        baseline_prefill_tokens_per_sec=baseline_prefill_tokens_per_sec,
        baseline_decode_tokens_per_sec=baseline_decode_tokens_per_sec,
        candidate_prefill_tokens_per_sec=candidate_prefill_tokens_per_sec,
        candidate_decode_tokens_per_sec=candidate_decode_tokens_per_sec,
    )
    return ObjectiveScore(objective=objective, score=value, components=components)


def geometric_mean(values: Sequence[float]) -> float:
    if not values:
        raise ScoreError("geometric mean requires at least one value")
    if any(value <= 0 or not math.isfinite(value) for value in values):
        raise ScoreError("geometric mean requires finite positive values")
    return math.exp(sum(math.log(value) for value in values) / len(values))


class CrossContextScore(FrozenModel):
    objective: Objective
    contexts: tuple[int, ...]
    per_context_scores: tuple[float, ...]
    score: float
    complete_coverage: bool

    @model_validator(mode="after")
    def _coverage(self) -> CrossContextScore:
        if len(self.contexts) != len(self.per_context_scores):
            raise ValueError("each context requires exactly one score")
        if self.contexts != tuple(sorted(set(self.contexts))):
            raise ValueError("contexts must be sorted and unique")
        if self.complete_coverage and not self.contexts:
            raise ValueError("complete coverage requires contexts")
        return self


def cross_context_score(
    objective: Objective,
    *,
    scores_by_context: dict[int, float],
    selected_contexts: Sequence[int],
) -> CrossContextScore:
    """Aggregate only over the exact complete selected context set.

    A missing context makes the aggregate ineligible; callers receive
    ``complete_coverage=False`` and must not present it as a global winner.
    """
    selected = tuple(sorted(set(int(context) for context in selected_contexts)))
    missing = [context for context in selected if context not in scores_by_context]
    present = tuple(context for context in selected if context in scores_by_context)
    values = tuple(scores_by_context[context] for context in present)
    complete = not missing and bool(selected)
    score = geometric_mean(values) if complete else 0.0
    return CrossContextScore(
        objective=objective,
        contexts=present,
        per_context_scores=values,
        score=score,
        complete_coverage=complete,
    )


def median(values: Sequence[float]) -> float:
    if not values:
        raise ScoreError("median requires at least one value")
    return float(statistics.median(values))


def percentile(values: Sequence[float], p: float) -> float:
    if not values:
        raise ScoreError("percentile requires at least one value")
    if not 0.0 <= p <= 100.0:
        raise ScoreError("percentile must be between 0 and 100")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * (p / 100.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction)


class ConfidenceInterval(FrozenModel):
    confidence_level: Probability
    lower: float
    upper: float
    point_estimate: float
    resamples: int
    sample_count: int
    method: NonEmptyStr = "paired_log_ratio_bootstrap_percentile"


def paired_log_ratio_ci(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    confidence_level: float = 0.95,
    resamples: int = 2000,
    seed: int = 20261020,
) -> ConfidenceInterval:
    """Deterministic paired bootstrap CI on log throughput ratios.

    Inputs are paired measurements in a consistent order. The point estimate
    is the geometric-mean ratio. The interval is the percentile bootstrap.
    """
    if len(baseline) != len(candidate) or len(baseline) < 2:
        raise ScoreError("paired bootstrap requires identical sample counts >= 2")
    if any(value <= 0 or not math.isfinite(value) for value in (*baseline, *candidate)):
        raise ScoreError("bootstrap inputs must be finite and positive")
    ratios = [
        candidate_value / baseline_value
        for baseline_value, candidate_value in zip(baseline, candidate, strict=True)
    ]
    point = geometric_mean(ratios)
    rng = random.Random(seed)
    count = len(ratios)
    estimates = []
    for _ in range(resamples):
        sample = [ratios[rng.randrange(count)] for _ in range(count)]
        estimates.append(geometric_mean(sample))
    alpha = (1.0 - confidence_level) / 2.0
    lower = percentile(estimates, alpha * 100.0)
    upper = percentile(estimates, (1.0 - alpha) * 100.0)
    return ConfidenceInterval(
        confidence_level=confidence_level,
        lower=lower,
        upper=upper,
        point_estimate=point,
        resamples=resamples,
        sample_count=count,
    )


class QualificationDecision(FrozenModel):
    qualified: bool
    score: float
    improvement_pct: float
    min_improvement_pct: float
    interval_lower: float
    confidence_level: Probability
    reasons: tuple[str, ...] = ()


def qualify_improvement(
    *,
    score: float,
    interval_lower: float,
    min_improvement_pct: float = 5.0,
    confidence_level: float = 0.95,
    guardrails_passed: bool = True,
) -> QualificationDecision:
    """Default gate: >=5% score improvement and CI strictly above baseline."""
    if not math.isfinite(score) or score <= 0:
        raise ScoreError("qualification requires a finite positive score")
    improvement_pct = (score - 1.0) * 100.0
    reasons: list[str] = []
    if not guardrails_passed:
        reasons.append("GUARDRAIL_REGRESSION")
    if improvement_pct < min_improvement_pct:
        reasons.append("BELOW_MINIMUM_IMPROVEMENT")
    if interval_lower <= 1.0:
        reasons.append("CONFIDENCE_INTERVAL_NOT_ABOVE_BASELINE")
    return QualificationDecision(
        qualified=not reasons,
        score=score,
        improvement_pct=improvement_pct,
        min_improvement_pct=min_improvement_pct,
        interval_lower=interval_lower,
        confidence_level=confidence_level,
        reasons=tuple(reasons),
    )
