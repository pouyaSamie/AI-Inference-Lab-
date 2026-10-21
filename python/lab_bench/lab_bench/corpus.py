"""Deterministic, non-secret benchmark corpus and tokenizer fitting.

The corpus is intentionally tiny in source form. Workloads repeat it to the
requested target and are then measured with the *target engine's* tokenizer, not
by character count. The SHA-256 in this module identifies the frozen corpus
unit so controller and worker can detect a dataset mismatch.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lab_core.ids import sha256_text

CORPUS_ID = "lab-synthetic-v1"
CORPUS_VERSION = "1"

_CORPUS_UNIT = (
    "The laboratory measures deterministic inference throughput using repeated, "
    "neutral text with no private data. "
)

# Frozen identity of the corpus unit. Prompt builders repeat this unit; they do
# not mutate it or substitute another dataset silently.
CORPUS_SHA256 = sha256_text(_CORPUS_UNIT)


class CorpusMismatch(ValueError):
    """The requested dataset identity does not match the frozen corpus."""


def corpus_unit() -> str:
    return _CORPUS_UNIT


def corpus_sha256() -> str:
    return CORPUS_SHA256


def verify_corpus(dataset_id: str | None, dataset_sha256: str | None) -> None:
    """Refuse an unknown dataset or a digest that does not match the corpus."""

    if dataset_id not in (None, CORPUS_ID):
        raise CorpusMismatch(f"unknown benchmark dataset {dataset_id!r}")
    if dataset_sha256 is not None and dataset_sha256 != CORPUS_SHA256:
        raise CorpusMismatch("benchmark dataset digest does not match the frozen corpus")


def render_corpus(characters: int, *, unit: str = _CORPUS_UNIT) -> str:
    """Repeat the frozen unit to at least ``characters`` ASCII characters."""

    if characters < 1:
        raise ValueError("characters must be positive")
    if not unit:
        raise ValueError("corpus unit must not be empty")
    repeats = max(1, -(-characters // len(unit)))
    return (unit * repeats)[:characters]


@dataclass(frozen=True)
class PromptFit:
    text: str
    token_count: int
    target_tokens: int
    iterations: int
    within_tolerance: bool
    tolerance: float

    @property
    def token_error(self) -> int:
        return self.token_count - self.target_tokens

    @property
    def relative_error(self) -> float:
        if self.target_tokens <= 0:
            return 0.0
        return abs(self.token_error) / self.target_tokens


# A callback keeps this module pure while allowing the worker to use the
# engine's HTTP tokenizer and tests to use a deterministic fake.
TokenCounter = Callable[[str], int]


def fit_prompt_to_tokens(
    target_tokens: int,
    count_tokens: TokenCounter,
    *,
    unit: str = _CORPUS_UNIT,
    tolerance: float = 0.01,
    max_iterations: int = 6,
) -> PromptFit:
    """Grow or shrink corpus text until the tokenizer is near the target.

    This is intentionally iterative: tokenizers are not linear in characters
    (templates, special tokens and multi-byte pieces all change the ratio). The
    caller must still verify the final request's usage and effective context.
    """

    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if not 0.0 < tolerance < 0.5:
        raise ValueError("tolerance must be in (0, 0.5)")
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")

    chars = max(len(unit), target_tokens * 4)
    text = render_corpus(chars, unit=unit)
    best: PromptFit | None = None
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        tokens = int(count_tokens(text))
        if tokens < 0:
            raise ValueError("tokenizer returned a negative token count")
        relative = abs(tokens - target_tokens) / target_tokens
        fit = PromptFit(
            text=text,
            token_count=tokens,
            target_tokens=target_tokens,
            iterations=iterations,
            within_tolerance=relative <= tolerance,
            tolerance=tolerance,
        )
        if best is None or fit.relative_error < best.relative_error:
            best = fit
        if fit.within_tolerance:
            return fit
        if tokens == 0:
            chars = max(len(text) * 2, len(unit))
        else:
            scaled = int(len(text) * target_tokens / tokens)
            # Always make progress when the ratio stalls on a plateau.
            chars = scaled if scaled != len(text) else len(text) + max(1, len(unit))
        chars = max(1, min(chars, 16 * 1024 * 1024))
        text = render_corpus(chars, unit=unit)
    assert best is not None
    return best
