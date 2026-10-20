"""Objective scoring contracts.

Only positive, comparable measurements produce scores. Missing or failed evidence
returns ``None``; it is never coerced to zero. Phase 5 adds bootstrap confidence
intervals and qualification gates on top of these primitives.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from lab_core.enums import Objective


@dataclass(frozen=True)
class ScoreInput:
    prefill_tokens_per_sec: float | None
    decode_tokens_per_sec: float | None

    def positive(self) -> bool:
        return any(
            value is not None and math.isfinite(value) and value > 0
            for value in (self.prefill_tokens_per_sec, self.decode_tokens_per_sec)
        )


def objective_ratio(objective: Objective, baseline: ScoreInput, candidate: ScoreInput) -> float | None:
    """Return the objective-specific ratio ``candidate / baseline``.

    Balanced uses the geometric mean of PP and TG ratios, matching the PRD.
    A missing component makes balanced undefined rather than silently substituting
    the other component.
    """
    pp0, tg0 = baseline.prefill_tokens_per_sec, baseline.decode_tokens_per_sec
    ppx, tgx = candidate.prefill_tokens_per_sec, candidate.decode_tokens_per_sec

    def valid(value: float | None) -> bool:
        return value is not None and math.isfinite(value) and value > 0

    if objective is Objective.PREFILL_MAX:
        if not (valid(pp0) and valid(ppx)):
            return None
        return ppx / pp0  # type: ignore[operator]
    if objective is Objective.GENERATION_MAX:
        if not (valid(tg0) and valid(tgx)):
            return None
        return tgx / tg0  # type: ignore[operator]
    if not (valid(pp0) and valid(tg0) and valid(ppx) and valid(tgx)):
        return None
    return math.sqrt((ppx / pp0) * (tgx / tg0))  # type: ignore[operator]


def geometric_mean(values: list[float]) -> float | None:
    if not values:
        return None
    if any(value <= 0 for value in values):
        return None
    return math.exp(sum(math.log(value) for value in values) / len(values))


def qualifies(
    ratio: float | None,
    *,
    minimum_improvement_ratio: float = 0.05,
    confidence_lower_bound: float | None = None,
) -> bool:
    """Default qualification gate: >=5% improvement and a CI strictly above 1.0.

    A lower bound must be supplied by the statistical layer; without it the result
    is at most screening evidence and this function returns False.
    """
    if ratio is None:
        return False
    if ratio < 1.0 + minimum_improvement_ratio:
        return False
    if confidence_lower_bound is None:
        return False
    return confidence_lower_bound > 1.0
