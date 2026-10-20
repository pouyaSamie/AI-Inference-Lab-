"""Typed adapter result helpers."""

from __future__ import annotations

from lab_core import (
    AwareTimestamp,
    BenchmarkObservation,
    FrozenModel,
    Identifier,
    Objective,
    QualityGate,
    Sha256,
    utcnow,
)


class ValidatedEvidence(FrozenModel):
    """Evidence passed to a pure recipe builder.

    A recipe may only be built from evidence that passed validation. The
    controller sets ``validated=True`` only after the relevant gates have
    passed; adapters do not decide that a simulation is a production result.
    """

    validated: bool
    experiment_id: Identifier
    objective: Objective
    candidate_id: Identifier
    observations: tuple[BenchmarkObservation, ...]
    quality_gates: tuple[QualityGate, ...] = ()
    confidence_ref: str | None = None
    metrics_ref: str = "artifacts/metrics.json"
    validated_at: AwareTimestamp = utcnow()
    notes: tuple[str, ...] = ()

    def observation_digests(self) -> tuple[Sha256, ...]:
        return tuple(observation.content_digest() for observation in self.observations)
