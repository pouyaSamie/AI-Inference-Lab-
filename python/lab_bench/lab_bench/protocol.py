"""Benchmark protocol and deterministic workload planning.

This is the Phase 1 foundation only: it defines the token-aware context
matrix, prompt-load levels and validation rules. Actual tokenizer-backed
corpora and HTTP execution belong to Phase 4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from lab_core.ids import sha256_hex, stable_id
from lab_core.version import WORKLOAD_PROTOCOL

from lab_core import ContextLength, FrozenModel, Identifier, NonEmptyStr, PositiveInt, Sha256, UnitFraction

CONTEXT_MATRIX: tuple[ContextLength, ...] = (
    ContextLength.K4,
    ContextLength.K8,
    ContextLength.K16,
    ContextLength.K32,
    ContextLength.K64,
    ContextLength.K128,
)

CONTEXT_LABELS: dict[ContextLength, str] = {
    ContextLength.K4: "4K",
    ContextLength.K8: "8K",
    ContextLength.K16: "16K",
    ContextLength.K32: "32K",
    ContextLength.K64: "64K",
    ContextLength.K128: "128K",
}


class ProtocolViolation(ValueError):
    pass


class PromptLoad(FrozenModel):
    name: NonEmptyStr
    fraction: UnitFraction
    target_input_tokens: PositiveInt
    output_tokens: PositiveInt
    reserved_tokens: PositiveInt


class WorkloadCase(FrozenModel):
    case_id: Identifier
    context: ContextLength
    prompt_fraction: float
    target_input_tokens: PositiveInt
    output_tokens: PositiveInt
    seed: int
    tokenizer_id: str | None = None
    protocol: NonEmptyStr = WORKLOAD_PROTOCOL

    def validate_case(self) -> None:
        if self.target_input_tokens + self.output_tokens > int(self.context):
            raise ProtocolViolation(
                f"case {self.case_id} exceeds context: "
                f"{self.target_input_tokens}+{self.output_tokens} > {int(self.context)}"
            )


@dataclass(frozen=True)
class ProtocolConfig:
    protocol: str = WORKLOAD_PROTOCOL
    fractions: tuple[float, ...] = (0.25, 0.60, 0.85, 0.98)
    output_tokens: int = 256
    near_capacity_fraction: float = 0.98


DEFAULT_PROTOCOL = ProtocolConfig()


def plan_workloads(
    context: ContextLength,
    *,
    config: ProtocolConfig = DEFAULT_PROTOCOL,
    tokenizer_id: str | None = None,
    seed: int = 42,
) -> tuple[WorkloadCase, ...]:
    """Plan prompt levels inside the configured usable context.

    The generated tokens plus a conservative template reserve are subtracted
    before computing input targets. This function does not claim tokenizer
    accuracy; Phase 4 must validate with the target engine tokenizer.
    """
    if config.output_tokens <= 0:
        raise ProtocolViolation("output_tokens must be positive")
    reserve = max(64, math.ceil(int(context) * 0.01))
    usable = int(context) - config.output_tokens - reserve
    if usable <= 0:
        raise ProtocolViolation(f"context {int(context)} cannot fit output tokens and template reserve")
    cases: list[WorkloadCase] = []
    for index, fraction in enumerate(config.fractions):
        if not 0.0 < fraction <= 1.0:
            raise ProtocolViolation("prompt fractions must be in (0, 1]")
        target = max(1, min(usable, int(usable * fraction)))
        case = WorkloadCase(
            case_id=stable_id("work", int(context), index, target, config.output_tokens, seed),
            context=context,
            prompt_fraction=fraction,
            target_input_tokens=target,
            output_tokens=config.output_tokens,
            seed=seed + index,
            tokenizer_id=tokenizer_id,
        )
        case.validate_case()
        cases.append(case)
    return tuple(cases)


def workload_digest(
    contexts: tuple[ContextLength, ...],
    config: ProtocolConfig = DEFAULT_PROTOCOL,
    *,
    seed: int = 42,
    dataset_sha256: Sha256 | None = None,
    tokenizer_id: str | None = None,
) -> str:
    return sha256_hex(
        {
            "protocol": config.protocol,
            "contexts": [int(context) for context in contexts],
            "fractions": list(config.fractions),
            "output_tokens": config.output_tokens,
            "seed": seed,
            "dataset_sha256": dataset_sha256,
            "tokenizer_id": tokenizer_id,
        }
    )


class ContextMeasurement(FrozenModel):
    """Observed token composition used to reject silent truncation."""

    context: ContextLength
    configured_context: PositiveInt
    effective_context: PositiveInt
    input_tokens: int
    output_tokens: int
    truncated: bool = False
    template_overhead_tokens: int = 0

    def validate_measurement(self) -> None:
        if self.truncated:
            raise ProtocolViolation("measurement reports truncation")
        if self.effective_context < self.configured_context:
            raise ProtocolViolation("effective context is below configured context")
        if self.input_tokens + self.output_tokens + self.template_overhead_tokens > self.effective_context:
            raise ProtocolViolation("measured token composition exceeds effective context")
