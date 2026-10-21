"""Offline tests for release impact classification and paired A/B records."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lab_core import (
    Backend,
    BenchSample,
    CapabilityDescriptor,
    CapabilityKind,
    ContextLength,
    EngineCapabilityManifest,
    EngineId,
    EngineIdentity,
    ImpactClass,
    ModelArtifact,
    ModelFile,
    Objective,
    WorkloadSuite,
)
from lab_updates import (
    ComparisonEvidence,
    ComparisonSample,
    ComparisonStatus,
    RecommendedAction,
    ReleaseMetadata,
    assess_release_impact,
    completed_comparison,
    evaluate_comparison,
    freeze_comparison,
)

NOW = datetime(2026, 10, 21, tzinfo=UTC)
CURRENT_SHA = "a" * 64
CANDIDATE_SHA = "b" * 64
MODEL_FILE_SHA = "d" * 64


def test_lab_updates_is_pure_without_process_network_or_filesystem_io() -> None:
    package = Path(__file__).resolve().parents[1] / "python/lab_updates/lab_updates"
    forbidden_imports = {
        "subprocess",
        "socket",
        "httpx",
        "requests",
        "urllib",
        "pathlib",
        "os",
        "shutil",
        "aiohttp",
    }
    forbidden_calls = {"open", "exec", "eval", "compile", "__import__"}
    for source in package.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_imports, source
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert node.module.split(".")[0] not in forbidden_imports, source
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls, source


def identity(*, version: str = "0.7.0-dev", build: str = "701", sha: str = CURRENT_SHA) -> EngineIdentity:
    return EngineIdentity(
        engine_id=EngineId.LLAMACPP,
        version=version,
        build=build,
        backend=Backend.CUDA,
        executable_id="llama-server",
        executable_sha256=sha,
        source_commit="dd002b91f" if sha == CURRENT_SHA else "candidate123",
    )


def manifest(
    engine: EngineIdentity,
    descriptors: tuple[CapabilityDescriptor, ...] = (),
) -> EngineCapabilityManifest:
    return EngineCapabilityManifest(
        engine=engine,
        backend=engine.backend,
        probed_at=NOW,
        descriptors=descriptors,
    )


def model(*, family: str | None = "qwen2.5", complete: bool = True) -> ModelArtifact:
    return ModelArtifact(
        model_id="qwen2.5-7b-instruct-q4_k_m",
        display_name="Qwen 2.5 7B",
        architecture="qwen2",
        model_family=family,
        quantization="Q4_K_M",
        files=(
            ModelFile(
                path="/models/qwen.gguf",
                sha256=MODEL_FILE_SHA if complete else None,
                size_bytes=4_000,
                verified=complete,
            ),
        ),
        verified=complete,
    )


def release(**overrides: object) -> ReleaseMetadata:
    values: dict[str, object] = {
        "engine_id": EngineId.LLAMACPP,
        "version": "0.7.1",
        "build": "702",
        "backend": Backend.CUDA,
        "executable_id": "llama-server",
        "source_commit": "candidate123",
        "artifact_sha256": CANDIDATE_SHA,
        "released_at": NOW,
        "changed_paths": ("ggml/src/ggml-cuda/mmq.cu",),
    }
    values.update(overrides)
    return ReleaseMetadata(**values)


def assessment(
    release_metadata: ReleaseMetadata,
    *,
    current: EngineCapabilityManifest | None = None,
    model_artifact: ModelArtifact | None = None,
):
    return assess_release_impact(
        release_metadata,
        worker_id="worker-1",
        model_id="qwen2.5-7b-instruct-q4_k_m",
        model=model_artifact or model(),
        current_manifest=current or manifest(identity(), ()),
        inventory_snapshot_revision=7,
        inventory_digest="e" * 64,
        gpu_uuids=("GPU-1",),
    )


def test_cuda_release_is_p0_and_requires_ab() -> None:
    result = assessment(release())
    assert result.applicable is True
    assert result.impact is ImpactClass.P0
    assert result.requires_smoke is True
    assert result.requires_ab is True
    assert result.recommended_action is RecommendedAction.TARGETED_RERUN
    assert "P0_RELEASE_AREA" in result.reasons
    assert result.current_engine == identity()
    assert result.candidate_engine_sha256 == CANDIDATE_SHA
    assert result.model_identity_complete is True


def test_incomplete_model_identity_blocks_comparison_creation() -> None:
    result = assessment(release(), model_artifact=model(complete=False))
    assert result.applicable is True
    assert result.requires_ab is True
    assert result.model_identity_complete is False
    assert result.model_digest is not None


def test_documentation_only_release_is_ignored() -> None:
    result = assessment(release(changed_paths=("docs/README.md",)))
    assert result.applicable is True
    assert result.impact is ImpactClass.P2
    assert result.requires_ab is False
    assert result.recommended_action is RecommendedAction.IGNORE


def test_unknown_path_fails_toward_smoke_testing() -> None:
    result = assessment(release(changed_paths=("src/mystery.cpp",)))
    assert result.impact is ImpactClass.P1
    assert result.requires_smoke is True
    assert result.requires_ab is True
    assert "IMPACT_UNCERTAIN_REQUIRES_SMOKE" in result.reasons


def test_unaffected_model_family_is_not_applicable() -> None:
    result = assessment(release(affected_model_families=("llama",)))
    assert result.applicable is False
    assert result.impact is ImpactClass.P2
    assert result.recommended_action is RecommendedAction.IGNORE
    assert "AFFECTED_MODEL_FAMILY_NOT_INSTALLED" in result.reasons


def test_capability_schema_change_raises_impact() -> None:
    old = CapabilityDescriptor(
        key="flash_attn",
        kind=CapabilityKind.ENUM,
        legal_values=("on", "off"),
        default="auto",
        impact_class=ImpactClass.P0,
    )
    new = old.model_copy(update={"default": "on"})
    candidate_engine = identity(version="0.7.1", build="702", sha=CANDIDATE_SHA)
    candidate_manifest = manifest(candidate_engine, (new,))
    release_metadata = release(
        changed_paths=("docs/release-notes.md",),
        capability_manifest=candidate_manifest,
    )
    result = assess_release_impact(
        release_metadata,
        worker_id="worker-1",
        model_id="qwen2.5-7b-instruct-q4_k_m",
        model=model(),
        current_manifest=manifest(identity(), (old,)),
        gpu_uuids=("GPU-1",),
    )
    assert result.impact is ImpactClass.P0
    assert result.capability_diff.changed == ("flash_attn",)
    assert result.requires_ab is True


def test_already_installed_release_is_not_an_upgrade() -> None:
    current = identity()
    result = assess_release_impact(
        release(
            version=current.version,
            build=current.build,
            source_commit=current.source_commit,
            artifact_sha256=current.executable_sha256,
        ),
        worker_id="worker-1",
        model_id="qwen2.5-7b-instruct-q4_k_m",
        model=model(),
        current_manifest=manifest(current, ()),
    )
    assert result.applicable is False
    assert result.recommended_action is RecommendedAction.IGNORE
    assert "RELEASE_ALREADY_INSTALLED" in result.reasons


def plan(*, contexts: tuple[ContextLength, ...] = (ContextLength.K4,)):
    workload = WorkloadSuite()
    return freeze_comparison(
        notice_id="rel_test",
        assessment_id="impact_test",
        worker_id="worker-1",
        model_id="qwen2.5-7b-instruct-q4_k_m",
        model_digest=model().artifact_digest,
        baseline_engine=identity(),
        candidate_engine=identity(version="0.7.1", build="702", sha=CANDIDATE_SHA),
        contexts=contexts,
        objective=Objective.BALANCED,
        workload=workload,
        gpu_uuids=("GPU-1",),
        min_improvement_pct=5.0,
        confidence_level=0.95,
    )


def sample(
    pair_index: int,
    *,
    baseline: tuple[float, float] = (100.0, 50.0),
    candidate: tuple[float, float] = (120.0, 60.0),
    context: ContextLength = ContextLength.K4,
    candidate_guardrail_passed: bool = True,
) -> ComparisonSample:
    del pair_index
    return ComparisonSample(
        context=context,
        baseline=BenchSample(
            prefill_tokens_per_sec=baseline[0],
            decode_tokens_per_sec=baseline[1],
        ),
        candidate=BenchSample(
            prefill_tokens_per_sec=candidate[0],
            decode_tokens_per_sec=candidate[1],
        ),
        candidate_guardrail_passed=candidate_guardrail_passed,
    )


def evidence(
    comparison_plan,
    samples: tuple[ComparisonSample, ...],
    *,
    simulated: bool = False,
) -> ComparisonEvidence:
    return ComparisonEvidence(
        comparison_id=comparison_plan.comparison_id,
        worker_id=comparison_plan.worker_id,
        model_digest=comparison_plan.model_digest,
        workload_digest=comparison_plan.workload.digest(),
        baseline_engine_sha256=comparison_plan.baseline_engine.executable_sha256,
        candidate_engine_sha256=comparison_plan.candidate_engine.executable_sha256,
        simulated=simulated,
        samples=samples,
    )


def test_improved_paired_evidence_never_approves_or_installs() -> None:
    comparison_plan = plan()
    result = evaluate_comparison(
        comparison_plan,
        evidence(comparison_plan, tuple(sample(index) for index in range(3))),
    )
    assert result.status is ComparisonStatus.IMPROVED
    assert result.contexts[0].status.value == "improved"
    assert result.recommendation.value == "review_candidate"
    assert result.upgrade_approved is False


def test_significant_regression_retains_current_engine() -> None:
    comparison_plan = plan()
    result = evaluate_comparison(
        comparison_plan,
        evidence(
            comparison_plan,
            tuple(sample(index, candidate=(80.0, 40.0)) for index in range(3)),
        ),
    )
    assert result.status is ComparisonStatus.REGRESSED
    assert result.contexts[0].status.value == "regressed"
    assert result.recommendation.value == "keep_current"
    assert result.upgrade_approved is False
    assert result.contexts[0].interval is not None
    assert result.contexts[0].interval.upper < 1.0


def test_candidate_guardrail_failure_is_a_regression() -> None:
    comparison_plan = plan()
    result = evaluate_comparison(
        comparison_plan,
        evidence(
            comparison_plan,
            tuple(sample(index, candidate_guardrail_passed=False) for index in range(3)),
        ),
    )
    assert result.status is ComparisonStatus.REGRESSED
    assert result.recommendation.value == "keep_current"
    assert "CANDIDATE_GUARDRAIL_FAILED" in result.reasons[0]


def test_small_change_is_inconclusive() -> None:
    comparison_plan = plan()
    result = evaluate_comparison(
        comparison_plan,
        evidence(
            comparison_plan,
            tuple(sample(index, candidate=(103.0, 51.5)) for index in range(3)),
        ),
    )
    assert result.status is ComparisonStatus.INCONCLUSIVE
    assert result.recommendation.value == "keep_current"
    assert result.upgrade_approved is False


def test_simulated_evidence_is_incompatible() -> None:
    comparison_plan = plan()
    result = evaluate_comparison(
        comparison_plan,
        evidence(
            comparison_plan,
            tuple(sample(index) for index in range(3)),
            simulated=True,
        ),
    )
    assert result.status is ComparisonStatus.INCOMPATIBLE
    assert "SIMULATED_EVIDENCE" in result.reasons


def test_missing_selected_context_and_mismatched_model_are_incompatible() -> None:
    comparison_plan = plan(contexts=(ContextLength.K4, ContextLength.K8))
    partial = evidence(comparison_plan, tuple(sample(index) for index in range(3)))
    result = evaluate_comparison(comparison_plan, partial)
    assert result.status is ComparisonStatus.INCOMPATIBLE
    assert any(reason.startswith("MISSING_CONTEXT:8192") for reason in result.reasons)

    mismatched = partial.model_copy(update={"model_digest": "f" * 64})
    result = evaluate_comparison(comparison_plan, mismatched)
    assert result.status is ComparisonStatus.INCOMPATIBLE
    assert "MODEL_DIGEST_MISMATCH" in result.reasons


def test_comparison_identity_binds_workload_and_gpu_selection() -> None:
    first = plan()
    second = freeze_comparison(
        notice_id=first.notice_id,
        assessment_id=first.assessment_id,
        worker_id=first.worker_id,
        model_id=first.model_id,
        model_digest=first.model_digest,
        baseline_engine=first.baseline_engine,
        candidate_engine=first.candidate_engine,
        contexts=first.contexts,
        objective=first.objective,
        workload=WorkloadSuite(repetitions=2),
        gpu_uuids=first.gpu_uuids,
        min_improvement_pct=first.min_improvement_pct,
        confidence_level=first.confidence_level,
    )
    assert first.comparison_id != second.comparison_id

    third = freeze_comparison(
        notice_id=first.notice_id,
        assessment_id=first.assessment_id,
        worker_id=first.worker_id,
        model_id=first.model_id,
        model_digest=first.model_digest,
        baseline_engine=first.baseline_engine,
        candidate_engine=first.candidate_engine,
        contexts=first.contexts,
        objective=first.objective,
        workload=first.workload,
        gpu_uuids=("GPU-2",),
        min_improvement_pct=first.min_improvement_pct,
        confidence_level=first.confidence_level,
    )
    assert first.comparison_id != third.comparison_id


def test_completed_comparison_rejects_changed_evidence() -> None:
    comparison_plan = plan()
    first = evidence(comparison_plan, tuple(sample(index) for index in range(3)))
    completed = completed_comparison(comparison_plan, first)
    replay = completed_comparison(completed, first)
    assert replay.evidence_digest == completed.evidence_digest

    changed = evidence(comparison_plan, tuple(sample(index, candidate=(90.0, 45.0)) for index in range(3)))
    with pytest.raises(ValueError, match="different evidence"):
        completed_comparison(completed, changed)
