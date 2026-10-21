"""Candidate configuration identity and deduplication."""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import (
    FrozenModel,
    Identifier,
    NonEmptyStr,
    NonNegativeInt,
    Parameters,
    PositiveInt,
    Sha256,
    parameters_digest,
)
from .enums import CandidateRole, CandidateState, ContextLength
from .ids import sha256_hex, stable_id
from .version import SCHEMA_VERSION


class CandidateSpec(FrozenModel):
    """A concrete, reproducible parameter vector for one trial and context.

    ``candidate_id`` is deterministic over engine hash, model digest, worker,
    context, workload digest and parameters, which makes duplicate proposals
    detectable across controller and optimizer restarts.
    """

    schema_version: NonEmptyStr = SCHEMA_VERSION
    candidate_id: Identifier = ""
    study_id: Identifier
    experiment_id: Identifier
    trial_number: NonNegativeInt
    engine_id: NonEmptyStr
    engine_sha256: Sha256
    model_digest: Sha256
    worker_id: Identifier
    context: ContextLength
    role: CandidateRole = CandidateRole.CANDIDATE
    parameters: Parameters = Field(default_factory=dict)
    parameter_digest: Sha256 | None = None
    workload_digest: Sha256
    state: CandidateState = CandidateState.PROPOSED
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _fill_identifiers(self) -> CandidateSpec:
        expected_params = parameters_digest(self.parameters)
        if self.parameter_digest is None:
            object.__setattr__(self, "parameter_digest", expected_params)
        elif self.parameter_digest != expected_params:
            raise ValueError("parameter_digest does not match parameters")
        expected_id = stable_id(
            "cand",
            self.engine_id,
            self.engine_sha256,
            self.model_digest,
            self.worker_id,
            int(self.context),
            self.workload_digest,
            self.parameters,
        )
        if self.candidate_id and self.candidate_id != expected_id:
            raise ValueError("candidate_id does not match the canonical candidate identity")
        object.__setattr__(self, "candidate_id", expected_id)
        return self

    def semantic_key(self) -> str:
        """Candidate identity independent of study/trial bookkeeping."""
        return sha256_hex(
            {
                "engine": self.engine_id,
                "engine_sha256": self.engine_sha256,
                "model_digest": self.model_digest,
                "worker_id": self.worker_id,
                "context": int(self.context),
                "workload_digest": self.workload_digest,
                "parameters": self.parameters,
            }
        )


class CandidateView(FrozenModel):
    candidate_id: Identifier
    study_id: Identifier
    experiment_id: Identifier
    trial_number: NonNegativeInt
    context: ContextLength
    parameters: Parameters
    parameter_digest: Sha256
    state: CandidateState
    created_at: str
    trial_state: str | None = None
    observation_id: Identifier | None = None


class TrialTell(FrozenModel):
    study_id: Identifier
    candidate_id: Identifier
    trial_number: PositiveInt
    state: str  # complete | fail | pruned
    value: float | None = None
    feasibility: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _value_for_complete(self) -> TrialTell:
        if self.state == "complete" and self.value is None:
            raise ValueError("completed trial requires an objective value")
        if self.state == "complete" and self.value is not None and self.value != self.value:  # NaN
            raise ValueError("objective value must not be NaN")
        return self
