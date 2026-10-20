"""Observation commit, feasibility ledger and optimizer tell-outbox."""

from __future__ import annotations

import math

from lab_core.base import utcnow
from lab_core.errors import ConflictError, NotFoundError
from lab_core.ids import sha256_hex
from sqlalchemy import select
from sqlalchemy.orm import Session

from lab_core import (
    BenchmarkObservation,
    CandidateState,
    EventType,
    FeasibilityOutcome,
    MeasurementStatus,
    Objective,
    ObservationStatus,
    OptimizerRequestKind,
    TellPayload,
    TrialTellState,
)

from ..config import Settings
from ..events import append_event
from ..orm import (
    CandidateRow,
    ExperimentRow,
    FeasibilityLedgerRow,
    ObservationRow,
    StudyRow,
)
from .optimizer_queue import enqueue_optimizer_request


def _screening_value(objective: Objective, observation: BenchmarkObservation) -> float | None:
    prefill = observation.metrics.prefill_tokens_per_sec
    decode = observation.metrics.decode_tokens_per_sec
    if objective is Objective.DECODE_MAX:
        value = decode
    elif objective is Objective.PREFILL_MAX:
        value = prefill
    else:
        value = math.sqrt(prefill * decode) if prefill and decode else None
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    return value


def _candidate_state(observation: BenchmarkObservation) -> CandidateState:
    if observation.status is ObservationStatus.COMPLETED:
        return CandidateState.OBSERVED
    if observation.status is ObservationStatus.RESOURCE_INFEASIBLE:
        return CandidateState.INFEASIBLE
    return CandidateState.FAILED


def commit_observation(
    session: Session,
    settings: Settings,
    observation: BenchmarkObservation,
) -> tuple[ObservationRow, bool]:
    existing = session.scalar(
        select(ObservationRow).where(ObservationRow.observation_id == observation.observation_id)
    )
    if existing is not None:
        if existing.content_digest == observation.content_digest():
            return existing, True
        raise ConflictError(
            "observation_id was already committed with different content",
            details={"observation_id": observation.observation_id},
        )

    experiment = session.get(ExperimentRow, observation.experiment_id)
    if experiment is None:
        raise NotFoundError("experiment not found")
    study = session.get(StudyRow, observation.study_id)
    if study is None:
        raise NotFoundError("study not found")
    candidate = session.get(CandidateRow, observation.candidate_id)
    if candidate is None or candidate.study_id != observation.study_id:
        raise NotFoundError("candidate not found for this study")
    if candidate.trial_number != observation.trial_number:
        raise ConflictError("observation trial number does not match the candidate")
    if candidate.context_tokens != int(observation.context):
        raise ConflictError("observation context does not match the candidate context")

    row = ObservationRow(
        observation_id=observation.observation_id,
        experiment_id=observation.experiment_id,
        study_id=observation.study_id,
        candidate_id=observation.candidate_id,
        trial_number=observation.trial_number,
        attempt=observation.attempt,
        context_tokens=int(observation.context),
        evidence_kind=observation.evidence_kind.value,
        measurement_status=observation.measurement_status.value,
        status=observation.status.value,
        simulated=observation.simulated,
        content_digest=observation.content_digest(),
        payload_json=observation.model_dump(mode="json"),
        committed_at=utcnow(),
    )
    session.add(row)

    candidate.state = _candidate_state(observation).value
    candidate.observation_id = observation.observation_id
    candidate.completed_at = utcnow()
    if observation.failure is not None and observation.failure.kind.value not in candidate.notes:
        candidate.notes = [*candidate.notes, observation.failure.kind.value]

    if observation.status is not ObservationStatus.COMPLETED or observation.measurement_status not in (
        MeasurementStatus.MEASURED,
        MeasurementStatus.SIMULATED,
        MeasurementStatus.SCREENING_ONLY,
    ):
        assumption = sha256_hex(
            {
                "candidate_id": candidate.candidate_id,
                "parameters": candidate.parameters_json,
                "context": candidate.context_tokens,
            }
        )
        session.add(
            FeasibilityLedgerRow(
                study_id=study.study_id,
                candidate_digest=candidate.semantic_digest,
                assumption_signature=assumption,
                outcome=(
                    FeasibilityOutcome.RESOURCE_INFEASIBLE.value
                    if observation.status is ObservationStatus.RESOURCE_INFEASIBLE
                    else FeasibilityOutcome.INCONCLUSIVE.value
                ),
                oom_stage=observation.failure.stage.value if observation.failure else "unknown",
                error_kind=observation.failure.kind.value if observation.failure else None,
                observed_vram_bytes=observation.metrics.gpu_vram_peak_bytes,
                observed_ram_bytes=observation.metrics.cpu_rss_peak_bytes,
                features_json={
                    "configured_context": observation.configured_context,
                    "effective_context": observation.effective_context,
                    "input_tokens": observation.input_tokens,
                    "output_tokens": observation.output_tokens,
                    "parameters": candidate.parameters_json,
                },
                created_at=utcnow(),
            )
        )

    append_event(
        session,
        experiment.experiment_id,
        EventType.OBSERVATION_COMMITTED,
        payload={
            "observation_id": observation.observation_id,
            "candidate_id": candidate.candidate_id,
            "trial_number": candidate.trial_number,
            "status": observation.status.value,
            "measurement_status": observation.measurement_status.value,
            "evidence_kind": observation.evidence_kind.value,
            "simulated": observation.simulated,
            "prefill_tokens_per_sec": observation.metrics.prefill_tokens_per_sec,
            "decode_tokens_per_sec": observation.metrics.decode_tokens_per_sec,
            "eligibility_reasons": observation.scoring_eligibility(),
        },
    )

    value = _screening_value(Objective(experiment.objective), observation)
    if observation.status is ObservationStatus.COMPLETED and value is not None:
        tell = TellPayload(
            study_id=study.study_id,
            study_name=study.study_name,
            candidate_id=candidate.candidate_id,
            trial_number=max(candidate.trial_number - 1, 0),
            state=TrialTellState.COMPLETE,
            value=value,
            feasibility=FeasibilityOutcome.FEASIBLE,
            reason="Phase 1 screening value from simulated/measured throughput",
        )
    else:
        failure_kind = observation.failure.kind.value if observation.failure else observation.status.value
        tell = TellPayload(
            study_id=study.study_id,
            study_name=study.study_name,
            candidate_id=candidate.candidate_id,
            trial_number=max(candidate.trial_number - 1, 0),
            state=TrialTellState.FAIL,
            value=None,
            feasibility=(
                FeasibilityOutcome.RESOURCE_INFEASIBLE
                if observation.status is ObservationStatus.RESOURCE_INFEASIBLE
                else FeasibilityOutcome.INCONCLUSIVE
            ),
            reason=f"trial did not produce a scoreable observation: {failure_kind}",
        )
    enqueue_optimizer_request(
        session,
        kind=OptimizerRequestKind.TELL,
        study_id=study.study_id,
        payload=tell,
        idempotency_key=f"tell:{candidate.candidate_id}",
    )
    session.flush()
    return row, False


def observation_model(row: ObservationRow) -> BenchmarkObservation:
    return BenchmarkObservation.model_validate(row.payload_json)
