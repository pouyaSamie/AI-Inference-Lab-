"""Offline finalization, paired confidence and qualification-gate tests."""

from __future__ import annotations

from lab_core import (
    Backend,
    BenchmarkObservation,
    BenchMetrics,
    BenchSample,
    CandidateRole,
    CandidateSpec,
    Classification,
    ContextLength,
    EngineId,
    EngineIdentity,
    EvidenceKind,
    ExperimentSpec,
    FinalizationStatus,
    MeasurementStatus,
    ModelArtifact,
    Objective,
    ObservationStatus,
    QualityGate,
    QualityGateStatus,
    RecipeMode,
    ResourceConstraints,
    SearchDepth,
    SearchPolicy,
    WorkloadSuite,
    finalize_experiment,
    objective_ratio,
    paired_ratio_ci,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _engine() -> EngineIdentity:
    return EngineIdentity(
        engine_id=EngineId.LLAMACPP,
        version="0.7.0-dev",
        build="701",
        backend=Backend.CUDA,
        executable_id="llama-server",
        executable_sha256=SHA_A,
    )


def _model() -> ModelArtifact:
    return ModelArtifact(
        model_id="test-model",
        display_name="Test Model",
        architecture="qwen2",
        quantization="Q4_K_M",
    )


def _spec(*, contexts: tuple[ContextLength, ...] = (ContextLength.K4,)) -> ExperimentSpec:
    return ExperimentSpec(
        worker_id="worker-1",
        engine=_engine(),
        model=_model(),
        objective=Objective.BALANCED,
        contexts=contexts,
        search_depth=SearchDepth.QUICK,
        search_policy=SearchPolicy(depth=SearchDepth.QUICK),
        constraints=ResourceConstraints(require_full_context_proof=True),
        workload=WorkloadSuite(),
        recipe_mode=(RecipeMode.CROSS_CONTEXT if len(contexts) > 1 else RecipeMode.PER_CONTEXT),
        inventory_snapshot_digest=SHA_B,
    )


def _candidate(
    *,
    role: CandidateRole,
    context: ContextLength,
    trial_number: int,
    threads: int,
) -> CandidateSpec:
    return CandidateSpec(
        study_id="study-1",
        experiment_id="exp-1",
        trial_number=trial_number,
        engine_id="llamacpp",
        engine_sha256=SHA_A,
        model_digest=_model().artifact_digest,
        worker_id="worker-1",
        context=context,
        role=role,
        parameters={"threads": threads},
        workload_digest=WorkloadSuite().digest(),
    )


def _observation(
    candidate: CandidateSpec,
    *,
    prefill: float,
    decode: float,
    simulated: bool = False,
) -> BenchmarkObservation:
    samples = tuple(
        BenchSample(
            prefill_tokens_per_sec=prefill * factor,
            decode_tokens_per_sec=decode * factor,
            time_to_first_token_ms=100.0 / factor,
            total_latency_ms=2_000.0 / factor,
        )
        for factor in (0.99, 1.0, 1.01)
    )
    return BenchmarkObservation(
        experiment_id=candidate.experiment_id,
        study_id=candidate.study_id,
        candidate_id=candidate.candidate_id,
        trial_number=candidate.trial_number,
        worker_id=candidate.worker_id,
        engine_id=candidate.engine_id,
        engine_sha256=candidate.engine_sha256,
        model_digest=candidate.model_digest,
        workload_digest=candidate.workload_digest,
        context=candidate.context,
        evidence_kind=EvidenceKind.SIMULATED if simulated else EvidenceKind.SERVER_API,
        measurement_status=(MeasurementStatus.SIMULATED if simulated else MeasurementStatus.MEASURED),
        status=ObservationStatus.COMPLETED,
        metrics=BenchMetrics(
            prefill_tokens_per_sec=prefill,
            decode_tokens_per_sec=decode,
            time_to_first_token_ms=100.0,
            total_latency_ms=2_000.0,
        ),
        configured_context=int(candidate.context),
        effective_context=int(candidate.context),
        input_tokens=2_048,
        output_tokens=256,
        repetitions=3,
        samples=samples,
        quality_gates=(
            QualityGate(name="context_truncation", status=QualityGateStatus.PASSED),
            QualityGate(name="planned_prompt_tokens", status=QualityGateStatus.PASSED),
        ),
        simulated=simulated,
    )


def test_paired_bootstrap_is_deterministic_and_orders_ratios() -> None:
    first = paired_ratio_ci([1.20, 1.21, 1.19])
    second = paired_ratio_ci([1.20, 1.21, 1.19])
    assert first == second
    assert first.point_estimate > 1.19
    assert first.lower > 1.10
    assert first.upper < 1.30

    baseline = (100.0, 100.0)
    candidate = (120.0, 120.0)
    assert (
        objective_ratio(
            Objective.BALANCED,
            baseline_prefill_tokens_per_sec=baseline[0],
            baseline_decode_tokens_per_sec=baseline[1],
            candidate_prefill_tokens_per_sec=candidate[0],
            candidate_decode_tokens_per_sec=candidate[1],
        )
        == 1.2
    )


def test_qualified_candidate_produces_a_validated_context_winner() -> None:
    spec = _spec()
    baseline = _candidate(
        role=CandidateRole.BASELINE,
        context=ContextLength.K4,
        trial_number=1,
        threads=8,
    )
    candidate = _candidate(
        role=CandidateRole.CANDIDATE,
        context=ContextLength.K4,
        trial_number=2,
        threads=16,
    )
    result = finalize_experiment(
        experiment_id="exp-1",
        spec=spec,
        candidates=(baseline, candidate),
        observations=(
            _observation(baseline, prefill=400.0, decode=40.0),
            _observation(candidate, prefill=500.0, decode=50.0),
        ),
    )
    assert result.classification is Classification.VALIDATED_WINNER
    assert result.validated_winner_candidate_id == candidate.candidate_id
    assert result.per_context[0].baseline_candidate_id == baseline.candidate_id
    evaluation = result.per_context[0].evaluations[0]
    assert evaluation.qualified is True
    assert evaluation.status is FinalizationStatus.VALIDATED
    assert evaluation.interval is not None
    assert evaluation.interval.lower > 1.05
    assert evaluation.candidate_samples == 3


def test_high_variance_candidate_is_inconclusive_not_a_winner() -> None:
    spec = _spec()
    baseline = _candidate(
        role=CandidateRole.BASELINE,
        context=ContextLength.K4,
        trial_number=1,
        threads=8,
    )
    candidate = _candidate(
        role=CandidateRole.CANDIDATE,
        context=ContextLength.K4,
        trial_number=2,
        threads=16,
    )
    baseline_observation = _observation(baseline, prefill=400.0, decode=40.0)
    noisy = _observation(candidate, prefill=500.0, decode=50.0).model_copy(
        update={
            "samples": (
                BenchSample(prefill_tokens_per_sec=220.0, decode_tokens_per_sec=22.0),
                BenchSample(prefill_tokens_per_sec=700.0, decode_tokens_per_sec=70.0),
                BenchSample(prefill_tokens_per_sec=500.0, decode_tokens_per_sec=50.0),
            )
        }
    )
    result = finalize_experiment(
        experiment_id="exp-1",
        spec=spec,
        candidates=(baseline, candidate),
        observations=(baseline_observation, noisy),
    )
    assert result.classification is Classification.NO_VALIDATED_WINNER
    assert result.validated_winner_candidate_id is None
    evaluation = result.per_context[0].evaluations[0]
    assert evaluation.qualified is False
    assert evaluation.status is FinalizationStatus.INCONCLUSIVE
    assert evaluation.interval is not None
    assert evaluation.interval.lower < 1.05


def test_cross_context_requires_full_selected_coverage() -> None:
    spec = _spec(contexts=(ContextLength.K4, ContextLength.K8))
    baseline_k4 = _candidate(
        role=CandidateRole.BASELINE,
        context=ContextLength.K4,
        trial_number=1,
        threads=8,
    )
    candidate_k4 = _candidate(
        role=CandidateRole.CANDIDATE,
        context=ContextLength.K4,
        trial_number=2,
        threads=16,
    )
    result = finalize_experiment(
        experiment_id="exp-1",
        spec=spec,
        candidates=(baseline_k4, candidate_k4),
        observations=(
            _observation(baseline_k4, prefill=400.0, decode=40.0),
            _observation(candidate_k4, prefill=500.0, decode=50.0),
        ),
    )
    cross = next(item for item in result.cross_context if item.candidate_id == candidate_k4.candidate_id)
    assert cross.complete_coverage is False
    assert cross.qualified is False
    assert result.validated_winner_candidate_id is None
    assert result.per_context[1].baseline_candidate_id is None
    assert "INCOMPLETE_CROSS_CONTEXT_COVERAGE" in result.warnings


def test_simulated_evidence_never_qualifies() -> None:
    spec = _spec()
    baseline = _candidate(
        role=CandidateRole.BASELINE,
        context=ContextLength.K4,
        trial_number=1,
        threads=8,
    )
    candidate = _candidate(
        role=CandidateRole.CANDIDATE,
        context=ContextLength.K4,
        trial_number=2,
        threads=16,
    )
    result = finalize_experiment(
        experiment_id="exp-1",
        spec=spec,
        candidates=(baseline, candidate),
        observations=(
            _observation(baseline, prefill=400.0, decode=40.0, simulated=True),
            _observation(candidate, prefill=500.0, decode=50.0, simulated=True),
        ),
    )
    assert result.classification is Classification.SIMULATED
    assert result.simulated is True
    assert result.validated_winner_candidate_id is None
    assert result.per_context[0].winner_candidate_id is None
    assert "SIMULATED_RESULTS_NOT_VALIDATED_FOR_DEPLOYMENT" in result.warnings
