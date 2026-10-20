"""Normalization helpers for native and serving evidence.

Adapters retain the original engine output; these helpers only derive typed,
comparable metrics and explicitly refuse to invent missing values.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from lab_core import BenchMetrics, ScoreError, median, percentile


def normalize_samples_ts(samples: Sequence[float]) -> dict[str, float]:
    """Derive robust dispersion from repeated native throughput samples."""
    values = [float(value) for value in samples]
    if not values:
        raise ScoreError("throughput sample list is empty")
    if any(value <= 0 or not math.isfinite(value) for value in values):
        raise ScoreError("throughput samples must be finite and positive")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return {
        "median": median(values),
        "mean": mean,
        "stddev": math.sqrt(variance),
        "p05": percentile(values, 5.0),
        "p95": percentile(values, 95.0),
        "sample_count": float(len(values)),
    }


def native_metrics(
    *,
    prefill_tokens_per_sec: float | None,
    decode_tokens_per_sec: float | None,
    samples_ts: Sequence[float] = (),
    extra: dict[str, float | int | None] | None = None,
) -> BenchMetrics:
    if prefill_tokens_per_sec is None and decode_tokens_per_sec is None:
        raise ScoreError("native observation requires at least one throughput measurement")
    unavailable: dict[str, str] = {}
    if prefill_tokens_per_sec is None:
        unavailable["prefill_tokens_per_sec"] = "native lane reported no prompt-processing measurement"
    if decode_tokens_per_sec is None:
        unavailable["decode_tokens_per_sec"] = "native lane reported no generation measurement"
    payload: dict[str, float | int | bool | None | dict[str, str]] = {
        "prefill_tokens_per_sec": prefill_tokens_per_sec,
        "decode_tokens_per_sec": decode_tokens_per_sec,
        "unavailable_reasons": unavailable,
    }
    if extra:
        payload.update(extra)
    return BenchMetrics.model_validate(payload)


def tokens_per_second(tokens: int, duration_ms: float) -> float:
    if tokens < 0:
        raise ScoreError("token count must not be negative")
    if duration_ms <= 0 or not math.isfinite(duration_ms):
        raise ScoreError("duration must be finite and positive")
    return tokens / (duration_ms / 1000.0)
