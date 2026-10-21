"""Paired old/new engine comparison records and deterministic qualification.

The comparison is a proposal: it freezes baseline/candidate identities, model
digest, worker, workloads and contexts before any evidence is accepted. A
positive result never approves or installs an engine; operator approval remains
a separate action.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from lab_core.ids import stable_id
from lab_core.scoring import objective_ratio, paired_ratio_ci, qualify_improvement
from pydantic import Field, field_validator, model_validator

from lab_core import (
    AwareTimestamp,
    BenchSample,
    ConfidenceInterval,
    ContextLength,
    EngineIdentity,
    FrozenModel,
    MeasurementStatus,
    NonEmptyStr,
    Objective,
    Probability,
    Sha256,
    WorkloadSuite,
    utcnow,
)


class ComparisonStatus(StrEnum):
    AWAITING_EVIDENCE = "awaiting_evidence"
    IMPROVED = "improved"
    REGRESSED = "regressed"
    INCONCLUSIVE = "inconclusive"
    INCOMPATIBLE = "incompatible"


TERMINAL_COMPARISON_STATUSES = frozenset(
    {
        ComparisonStatus.IMPROVED,
        ComparisonStatus.REGRESSED,
        ComparisonStatus.INCONCLUSIVE,
        ComparisonStatus.INCOMPATIBLE,
    }
)


class ContextComparisonStatus(StrEnum):
    IMPROVED = "improved"
    REGRESSED = "regressed"
    INCONCLUSIVE = "inconclusive"


class ComparisonRecommendation(StrEnum):
    KEEP_CURRENT = "keep_current"
    REVIEW_CANDIDATE = "review_candidate"


class ComparisonSample(FrozenModel):
    context: ContextLength
    baseline: BenchSample
    candidate: BenchSample
    baseline_guardrail_passed: bool = True
    candidate_guardrail_passed: bool = True
    notes: tuple[NonEmptyStr, ...] = ()


class ComparisonEvidence(FrozenModel):
    schema_version: NonEmptyStr = "1.0.0"
    comparison_id: NonEmptyStr
    worker_id: NonEmptyStr
    model_digest: Sha256
    workload_digest: Sha256
    baseline_engine_sha256: Sha256
    candidate_engine_sha256: Sha256
    simulated: bool = False
    measurement_status: MeasurementStatus = MeasurementStatus.MEASURED
    samples: tuple[ComparisonSample, ...] = Field(default_factory=tuple, max_length=5_000)
    notes: tuple[NonEmptyStr, ...] = ()


class ContextComparisonResult(FrozenModel):
    context: ContextLength
    status: ContextComparisonStatus
    score: float | None = None
    improvement_pct: float | None = None
    sample_count: int = 0
    interval: ConfidenceInterval | None = None
    reasons: tuple[NonEmptyStr, ...] = ()


class ComparisonResult(FrozenModel):
    schema_version: NonEmptyStr = "1.0.0"
    comparison_id: NonEmptyStr
    status: ComparisonStatus
    objective: Objective
    min_improvement_pct: float = 5.0
    confidence_level: Probability = 0.95
    contexts: tuple[ContextComparisonResult, ...] = ()
    reasons: tuple[NonEmptyStr, ...] = ()
    recommendation: ComparisonRecommendation = ComparisonRecommendation.KEEP_CURRENT
    upgrade_approved: Literal[False] = False
    evaluated_at: AwareTimestamp = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _terminal(self) -> ComparisonResult:
        if self.status is ComparisonStatus.AWAITING_EVIDENCE:
            raise ValueError("a final comparison result cannot remain awaiting_evidence")
        if self.status is ComparisonStatus.IMPROVED and not all(
            item.status is ContextComparisonStatus.IMPROVED for item in self.contexts
        ):
            raise ValueError("every selected context must be improved")
        return self


class ComparisonPlan(FrozenModel):
    schema_version: NonEmptyStr = "1.0.0"
    comparison_id: NonEmptyStr
    notice_id: NonEmptyStr
    assessment_id: NonEmptyStr
    worker_id: NonEmptyStr
    model_id: NonEmptyStr
    model_digest: Sha256
    baseline_engine: EngineIdentity
    candidate_engine: EngineIdentity
    contexts: tuple[ContextLength, ...]
    objective: Objective
    workload: WorkloadSuite = Field(default_factory=WorkloadSuite)
    gpu_uuids: tuple[NonEmptyStr, ...] = ()
    min_improvement_pct: float = Field(default=5.0, ge=0.0, le=100.0)
    confidence_level: Probability = 0.95
    status: ComparisonStatus = ComparisonStatus.AWAITING_EVIDENCE
    result: ComparisonResult | None = None
    evidence_digest: Sha256 | None = None
    created_at: AwareTimestamp = Field(default_factory=utcnow)
    evaluated_at: AwareTimestamp | None = None

    @field_validator("contexts")
    @classmethod
    def _contexts_canonical(cls, value: tuple[ContextLength, ...]) -> tuple[ContextLength, ...]:
        if not value:
            raise ValueError("at least one comparison context is required")
        ordered = tuple(sorted(set(value), key=int))
        if len(ordered) != len(value):
            raise ValueError("comparison contexts must be unique")
        return ordered

    @field_validator("gpu_uuids")
    @classmethod
    def _gpus_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("gpu_uuids must be unique")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> ComparisonPlan:
        if self.baseline_engine.executable_sha256 == self.candidate_engine.executable_sha256:
            raise ValueError("baseline and candidate engine hashes must differ")
        if self.baseline_engine.engine_id != self.candidate_engine.engine_id:
            raise ValueError("comparison engines must belong to the same engine id")
        if self.status in TERMINAL_COMPARISON_STATUSES:
            if self.result is None:
                raise ValueError("terminal comparison requires a result")
            if self.result.status is not self.status:
                raise ValueError("comparison status and result status must match")
        elif self.result is not None:
            raise ValueError("non-terminal comparison cannot have a final result")
        return self


def comparison_id(
    *,
    notice_id: str,
    assessment_id: str,
    worker_id: str,
    model_id: str,
    model_digest: str,
    baseline_engine_sha256: str,
    candidate_engine_sha256: str,
    contexts: tuple[int, ...],
    objective: Objective,
    workload_digest: str,
    gpu_uuids: tuple[str, ...],
    min_improvement_pct: float,
    confidence_level: float,
) -> str:
    return stable_id(
        "cmp",
        notice_id,
        assessment_id,
        worker_id,
        model_id,
        model_digest,
        baseline_engine_sha256,
        candidate_engine_sha256,
        tuple(sorted(set(contexts))),
        objective.value,
        workload_digest,
        tuple(sorted(set(gpu_uuids))),
        min_improvement_pct,
        confidence_level,
    )


def evidence_digest(evidence: ComparisonEvidence) -> str:
    return evidence.digest()


def evaluate_comparison(plan: ComparisonPlan, evidence: ComparisonEvidence) -> ComparisonResult:
    """Classify paired evidence against the frozen proposal.

    Missing, simulated, stale-identity or incompatible evidence never becomes a
    pass. A statistically significant >5% drop is a regression even when other
    contexts improve.
    """

    incompatible: list[str] = []
    if evidence.comparison_id != plan.comparison_id:
        incompatible.append("COMPARISON_ID_MISMATCH")
    if evidence.worker_id != plan.worker_id:
        incompatible.append("WORKER_MISMATCH")
    if evidence.model_digest != plan.model_digest:
        incompatible.append("MODEL_DIGEST_MISMATCH")
    if evidence.workload_digest != plan.workload.digest():
        incompatible.append("WORKLOAD_DIGEST_MISMATCH")
    if evidence.baseline_engine_sha256 != plan.baseline_engine.executable_sha256:
        incompatible.append("BASELINE_ENGINE_MISMATCH")
    if evidence.candidate_engine_sha256 != plan.candidate_engine.executable_sha256:
        incompatible.append("CANDIDATE_ENGINE_MISMATCH")
    if evidence.simulated:
        incompatible.append("SIMULATED_EVIDENCE")
    if evidence.measurement_status is not MeasurementStatus.MEASURED:
        incompatible.append(f"MEASUREMENT_{evidence.measurement_status.value.upper()}")

    selected = {int(context) for context in plan.contexts}
    present = {int(sample.context) for sample in evidence.samples}
    for context in sorted(selected - present):
        incompatible.append(f"MISSING_CONTEXT:{context}")
    for context in sorted(present - selected):
        incompatible.append(f"UNEXPECTED_CONTEXT:{context}")

    if incompatible:
        return ComparisonResult(
            comparison_id=plan.comparison_id,
            status=ComparisonStatus.INCOMPATIBLE,
            objective=plan.objective,
            min_improvement_pct=plan.min_improvement_pct,
            confidence_level=plan.confidence_level,
            reasons=tuple(dict.fromkeys(incompatible)),
            recommendation=ComparisonRecommendation.KEEP_CURRENT,
        )

    by_context: dict[int, list[ComparisonSample]] = {int(item): [] for item in plan.contexts}
    for sample in evidence.samples:
        by_context[int(sample.context)].append(sample)

    baseline_failed = [
        int(sample.context) for sample in evidence.samples if not sample.baseline_guardrail_passed
    ]
    if baseline_failed:
        return ComparisonResult(
            comparison_id=plan.comparison_id,
            status=ComparisonStatus.INCOMPATIBLE,
            objective=plan.objective,
            min_improvement_pct=plan.min_improvement_pct,
            confidence_level=plan.confidence_level,
            reasons=tuple(
                dict.fromkeys(
                    f"BASELINE_GUARDRAIL_FAILED:{context}" for context in sorted(set(baseline_failed))
                )
            ),
            recommendation=ComparisonRecommendation.KEEP_CURRENT,
        )

    context_results: list[ContextComparisonResult] = []
    for context in plan.contexts:
        samples = by_context[int(context)]
        reasons: list[str] = []
        candidate_guardrail = all(sample.candidate_guardrail_passed for sample in samples)
        if not candidate_guardrail:
            reasons.append("CANDIDATE_GUARDRAIL_FAILED")
        if len(samples) < 2:
            insufficient_status = (
                ContextComparisonStatus.REGRESSED
                if not candidate_guardrail
                else ContextComparisonStatus.INCONCLUSIVE
            )
            context_results.append(
                ContextComparisonResult(
                    context=context,
                    status=insufficient_status,
                    sample_count=len(samples),
                    reasons=tuple((*reasons, "INSUFFICIENT_PAIRED_SAMPLES")),
                )
            )
            continue
        ratios = [
            objective_ratio(
                plan.objective,
                baseline_prefill_tokens_per_sec=sample.baseline.prefill_tokens_per_sec,
                baseline_decode_tokens_per_sec=sample.baseline.decode_tokens_per_sec,
                candidate_prefill_tokens_per_sec=sample.candidate.prefill_tokens_per_sec,
                candidate_decode_tokens_per_sec=sample.candidate.decode_tokens_per_sec,
            )
            for sample in samples
        ]
        interval = paired_ratio_ci(
            ratios,
            confidence_level=plan.confidence_level,
            resamples=2_000,
            seed=20261020 + int(context),
        )
        qualification = qualify_improvement(
            score=interval.point_estimate,
            interval_lower=interval.lower,
            min_improvement_pct=plan.min_improvement_pct,
            confidence_level=plan.confidence_level,
            guardrails_passed=candidate_guardrail,
        )
        regression_threshold = 1.0 - plan.min_improvement_pct / 100.0
        regressed = interval.upper < 1.0 and interval.point_estimate <= regression_threshold
        if not candidate_guardrail:
            context_status = ContextComparisonStatus.REGRESSED
        elif regressed:
            context_status = ContextComparisonStatus.REGRESSED
            reasons.append("SIGNIFICANT_REGRESSION")
        elif qualification.qualified:
            context_status = ContextComparisonStatus.IMPROVED
        else:
            context_status = ContextComparisonStatus.INCONCLUSIVE
            reasons.extend(qualification.reasons)
        context_results.append(
            ContextComparisonResult(
                context=context,
                status=context_status,
                score=interval.point_estimate,
                improvement_pct=(interval.point_estimate - 1.0) * 100.0,
                sample_count=len(samples),
                interval=interval,
                reasons=tuple(dict.fromkeys(reasons)),
            )
        )

    results = tuple(context_results)
    if any(item.status is ContextComparisonStatus.REGRESSED for item in results):
        overall_status = ComparisonStatus.REGRESSED
        recommendation = ComparisonRecommendation.KEEP_CURRENT
    elif results and all(item.status is ContextComparisonStatus.IMPROVED for item in results):
        overall_status = ComparisonStatus.IMPROVED
        recommendation = ComparisonRecommendation.REVIEW_CANDIDATE
    else:
        overall_status = ComparisonStatus.INCONCLUSIVE
        recommendation = ComparisonRecommendation.KEEP_CURRENT
    aggregate_reasons = tuple(
        dict.fromkeys(f"{item.context}:{reason}" for item in results for reason in item.reasons)
    )
    return ComparisonResult(
        comparison_id=plan.comparison_id,
        status=overall_status,
        objective=plan.objective,
        min_improvement_pct=plan.min_improvement_pct,
        confidence_level=plan.confidence_level,
        contexts=results,
        reasons=aggregate_reasons,
        recommendation=recommendation,
    )


def freeze_comparison(
    *,
    notice_id: str,
    assessment_id: str,
    worker_id: str,
    model_id: str,
    model_digest: str,
    baseline_engine: EngineIdentity,
    candidate_engine: EngineIdentity,
    contexts: tuple[ContextLength, ...],
    objective: Objective,
    workload: WorkloadSuite,
    gpu_uuids: tuple[str, ...],
    min_improvement_pct: float,
    confidence_level: float,
) -> ComparisonPlan:
    identifier = comparison_id(
        notice_id=notice_id,
        assessment_id=assessment_id,
        worker_id=worker_id,
        model_id=model_id,
        model_digest=model_digest,
        baseline_engine_sha256=baseline_engine.executable_sha256,
        candidate_engine_sha256=candidate_engine.executable_sha256,
        contexts=tuple(int(item) for item in contexts),
        objective=objective,
        workload_digest=workload.digest(),
        gpu_uuids=gpu_uuids,
        min_improvement_pct=min_improvement_pct,
        confidence_level=confidence_level,
    )
    return ComparisonPlan(
        comparison_id=identifier,
        notice_id=notice_id,
        assessment_id=assessment_id,
        worker_id=worker_id,
        model_id=model_id,
        model_digest=model_digest,
        baseline_engine=baseline_engine,
        candidate_engine=candidate_engine,
        contexts=contexts,
        objective=objective,
        workload=workload,
        gpu_uuids=gpu_uuids,
        min_improvement_pct=min_improvement_pct,
        confidence_level=confidence_level,
    )


def completed_comparison(plan: ComparisonPlan, evidence: ComparisonEvidence) -> ComparisonPlan:
    digest = evidence_digest(evidence)
    if plan.evidence_digest is not None and plan.evidence_digest != digest:
        raise ValueError("comparison already has different evidence")
    result = evaluate_comparison(plan, evidence)
    now = utcnow()
    return plan.model_copy(
        update={
            "status": result.status,
            "result": result,
            "evidence_digest": digest,
            "evaluated_at": now,
        }
    )
