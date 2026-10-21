"""Pure release metadata and deterministic impact classification.

This module never performs network access, starts a process or touches an
installed binary. Imported release metadata is evidence only until an operator
runs an explicit smoke/A-B comparison.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from lab_core.ids import stable_id
from pydantic import Field, field_validator, model_validator

from lab_core import (
    AwareTimestamp,
    Backend,
    CapabilityDescriptor,
    EngineCapabilityManifest,
    EngineId,
    EngineIdentity,
    FrozenModel,
    ImpactClass,
    ModelArtifact,
    NonEmptyStr,
    NonNegativeInt,
    Sha256,
    utcnow,
)

IMPACT_POLICY_VERSION = "release-impact-v1"


class ReleaseSource(StrEnum):
    OFFLINE_IMPORT = "offline_import"
    MANUAL = "manual"
    GITHUB_RELEASE = "github_release"


class ChangedArea(StrEnum):
    CUDA_KERNEL = "cuda_kernel"
    BACKEND_SELECTION = "backend_selection"
    MOE = "moe"
    KV_CACHE = "kv_cache"
    CONTEXT = "context"
    MODEL_LOADER = "model_loader"
    SCHEDULING = "scheduling"
    THREADING = "threading"
    BATCHING = "batching"
    SERVER_API = "server_api"
    DOCUMENTATION = "documentation"
    TEST_ONLY = "test_only"
    GPU_ARCH = "gpu_arch"
    OTHER = "other"
    UNKNOWN = "unknown"


class RecommendedAction(StrEnum):
    IGNORE = "ignore"
    SMOKE_TEST = "smoke_test"
    TARGETED_RERUN = "targeted_rerun"
    FULL_RERUN = "full_rerun"


class ReleaseDecision(StrEnum):
    PENDING = "pending"
    PINNED = "pinned"
    DEFERRED = "deferred"
    COMPARISON_REQUESTED = "comparison_requested"


class ReleaseAsset(FrozenModel):
    """Metadata for one official release asset. It is never downloaded here."""

    name: NonEmptyStr
    platform: NonEmptyStr | None = None
    sha256: Sha256 | None = None
    size_bytes: NonNegativeInt | None = None
    url: NonEmptyStr | None = None

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("https://", "http://")):
            raise ValueError("asset URL must use http or https")
        return value


class ReleaseMetadata(FrozenModel):
    """Operator-supplied release facts.

    A pinned local checkout, release feed or official manifest may populate this
    model. ``capability_manifest`` is optional and must describe the candidate
    build when present; it is not treated as an installed observation.
    """

    engine_id: EngineId
    version: NonEmptyStr
    build: NonEmptyStr
    backend: Backend = Backend.UNKNOWN
    executable_id: NonEmptyStr | None = None
    source_commit: NonEmptyStr | None = None
    artifact_sha256: Sha256 | None = None
    released_at: AwareTimestamp
    source: ReleaseSource = ReleaseSource.OFFLINE_IMPORT
    source_url: NonEmptyStr | None = None
    changelog: NonEmptyStr | None = None
    changed_paths: tuple[NonEmptyStr, ...] = Field(default_factory=tuple, max_length=2_000)
    changed_areas: tuple[ChangedArea, ...] = Field(default_factory=tuple, max_length=64)
    affected_model_families: tuple[NonEmptyStr, ...] = Field(default_factory=tuple, max_length=64)
    assets: tuple[ReleaseAsset, ...] = Field(default_factory=tuple, max_length=100)
    capability_manifest: EngineCapabilityManifest | None = None
    notes: tuple[NonEmptyStr, ...] = Field(default_factory=tuple, max_length=100)

    @field_validator("source_url")
    @classmethod
    def _source_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("https://", "http://")):
            raise ValueError("release source URL must use http or https")
        return value

    @field_validator("changed_paths")
    @classmethod
    def _unique_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("changed_paths must be unique")
        return value

    @field_validator("changed_areas", "affected_model_families")
    @classmethod
    def _unique_values(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        if len(set(value)) != len(value):
            raise ValueError("release metadata lists must be unique")
        return value

    @model_validator(mode="after")
    def _manifest_matches(self) -> ReleaseMetadata:
        if self.capability_manifest is None:
            return self
        manifest = self.capability_manifest.engine
        if manifest.engine_id != self.engine_id:
            raise ValueError("capability manifest belongs to a different engine")
        if manifest.version != self.version or manifest.build != self.build:
            raise ValueError("capability manifest version/build does not match the release")
        if self.artifact_sha256 is not None and manifest.executable_sha256 != self.artifact_sha256:
            raise ValueError("capability manifest executable hash does not match artifact_sha256")
        if self.executable_id is not None and manifest.executable_id != self.executable_id:
            raise ValueError("capability manifest executable_id does not match the release")
        return self

    @property
    def notice_id(self) -> str:
        return release_notice_id(self)

    @property
    def candidate_executable_sha256(self) -> Sha256 | None:
        if self.artifact_sha256 is not None:
            return self.artifact_sha256
        if self.capability_manifest is not None:
            return self.capability_manifest.engine.executable_sha256
        return None


def release_notice_id(release: ReleaseMetadata) -> str:
    """Stable notice identity over every imported release fact."""

    return stable_id("rel", release.digest())


class CapabilityDiff(FrozenModel):
    added: tuple[NonEmptyStr, ...] = ()
    removed: tuple[NonEmptyStr, ...] = ()
    changed: tuple[NonEmptyStr, ...] = ()
    impact_class: ImpactClass = ImpactClass.P2

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    @classmethod
    def between(
        cls,
        current: EngineCapabilityManifest | None,
        candidate: EngineCapabilityManifest | None,
    ) -> CapabilityDiff:
        if current is None or candidate is None:
            return cls()
        current_by_key = {item.key: item for item in current.descriptors}
        candidate_by_key = {item.key: item for item in candidate.descriptors}
        added = tuple(sorted(set(candidate_by_key) - set(current_by_key)))
        removed = tuple(sorted(set(current_by_key) - set(candidate_by_key)))
        changed = tuple(
            sorted(
                key
                for key in set(current_by_key) & set(candidate_by_key)
                if _descriptor_signature(current_by_key[key]) != _descriptor_signature(candidate_by_key[key])
            )
        )
        impact = ImpactClass.P2
        for key in (*added, *removed, *changed):
            descriptor = candidate_by_key.get(key) or current_by_key.get(key)
            if descriptor is not None:
                impact = stronger_impact(impact, descriptor.impact_class)
        if impact is ImpactClass.P2 and (added or removed or changed):
            impact = ImpactClass.P1
        return cls(added=added, removed=removed, changed=changed, impact_class=impact)


def _descriptor_signature(descriptor: CapabilityDescriptor) -> tuple[Any, ...]:
    return (
        descriptor.kind.value,
        descriptor.support.value,
        tuple(descriptor.legal_values),
        descriptor.minimum,
        descriptor.maximum,
        descriptor.step,
        descriptor.default,
        descriptor.constraints,
        descriptor.incompatibilities,
        descriptor.impact_class.value,
        descriptor.restart_required,
        descriptor.quality_risk,
    )


_AREA_IMPACT: dict[ChangedArea, ImpactClass] = {
    ChangedArea.CUDA_KERNEL: ImpactClass.P0,
    ChangedArea.BACKEND_SELECTION: ImpactClass.P0,
    ChangedArea.MOE: ImpactClass.P0,
    ChangedArea.KV_CACHE: ImpactClass.P0,
    ChangedArea.CONTEXT: ImpactClass.P0,
    ChangedArea.MODEL_LOADER: ImpactClass.P0,
    ChangedArea.SCHEDULING: ImpactClass.P1,
    ChangedArea.THREADING: ImpactClass.P1,
    ChangedArea.BATCHING: ImpactClass.P1,
    ChangedArea.SERVER_API: ImpactClass.P1,
    ChangedArea.DOCUMENTATION: ImpactClass.P2,
    ChangedArea.TEST_ONLY: ImpactClass.P2,
    ChangedArea.GPU_ARCH: ImpactClass.P2,
    ChangedArea.OTHER: ImpactClass.P1,
    ChangedArea.UNKNOWN: ImpactClass.P1,
}

_IMPACT_RANK = {ImpactClass.P2: 0, ImpactClass.P1: 1, ImpactClass.P0: 2}


def stronger_impact(left: ImpactClass, right: ImpactClass) -> ImpactClass:
    return left if _IMPACT_RANK[left] >= _IMPACT_RANK[right] else right


def classify_path(path: str) -> ChangedArea:
    """Classify one repository path with deterministic, documented patterns."""

    normalized = path.strip().lower().replace("\\", "/")
    if not normalized:
        return ChangedArea.UNKNOWN
    if (
        normalized.startswith(("docs/", "examples/", "scripts/docs/"))
        or normalized.endswith((".md", ".rst", ".txt"))
        or "/docs/" in normalized
    ):
        return ChangedArea.DOCUMENTATION
    if normalized.startswith(("tests/", "test/")) or "/tests/" in normalized or "/test/" in normalized:
        return ChangedArea.TEST_ONLY
    if any(
        token in normalized
        for token in (
            "ggml-cuda",
            "cuda",
            "rocm",
            "hip",
            "metal",
            "vulkan",
            "kernel",
            "gpu",
            "backend",
        )
    ):
        return ChangedArea.CUDA_KERNEL if "backend" not in normalized else ChangedArea.BACKEND_SELECTION
    if any(token in normalized for token in ("moe", "expert")):
        return ChangedArea.MOE
    if any(token in normalized for token in ("kv-cache", "kv_cache", "kv cache", "cache")):
        return ChangedArea.KV_CACHE
    if any(token in normalized for token in ("context", "rope", "attention", "kv")):
        return ChangedArea.CONTEXT
    if any(
        token in normalized for token in ("model-loader", "model_loader", "loader", "llama-model", "quant")
    ):
        return ChangedArea.MODEL_LOADER
    if any(token in normalized for token in ("scheduler", "queue", "slot")):
        return ChangedArea.SCHEDULING
    if any(token in normalized for token in ("thread", "parallel")):
        return ChangedArea.THREADING
    if any(token in normalized for token in ("batch", "ubatch")):
        return ChangedArea.BATCHING
    if any(token in normalized for token in ("server", "api", "http", "sampling", "grammar", "chat")):
        return ChangedArea.SERVER_API
    return ChangedArea.UNKNOWN


def changed_areas_for(release: ReleaseMetadata) -> tuple[ChangedArea, ...]:
    areas = set(release.changed_areas)
    areas.update(classify_path(path) for path in release.changed_paths)
    if not areas:
        areas.add(ChangedArea.UNKNOWN)
    # An explicit documentation/test-only classification cannot hide a path
    # that clearly touches runtime code. Kernel/loader areas already outrank it.
    if areas.intersection(
        {
            ChangedArea.CUDA_KERNEL,
            ChangedArea.BACKEND_SELECTION,
            ChangedArea.MOE,
            ChangedArea.KV_CACHE,
            ChangedArea.CONTEXT,
            ChangedArea.MODEL_LOADER,
        }
    ):
        areas.discard(ChangedArea.DOCUMENTATION)
        areas.discard(ChangedArea.TEST_ONLY)
        areas.discard(ChangedArea.GPU_ARCH)
    return tuple(sorted(areas, key=lambda item: item.value))


def classify_release_impact(release: ReleaseMetadata) -> tuple[ImpactClass, tuple[ChangedArea, ...]]:
    areas = changed_areas_for(release)
    impact = ImpactClass.P2
    for area in areas:
        impact = stronger_impact(impact, _AREA_IMPACT[area])
    return impact, areas


class ImpactAssessment(FrozenModel):
    """Deterministic applicability result for one worker/model context."""

    schema_version: NonEmptyStr = "1.0.0"
    assessment_id: NonEmptyStr
    notice_id: NonEmptyStr
    worker_id: NonEmptyStr
    model_id: NonEmptyStr | None = None
    model_digest: Sha256 | None = None
    model_identity_complete: bool = False
    engine_id: EngineId
    current_engine: EngineIdentity | None = None
    candidate_engine_sha256: Sha256 | None = None
    inventory_snapshot_revision: NonNegativeInt = 0
    inventory_digest: Sha256 | None = None
    inventory_fresh: bool = True
    applicable: bool
    impact: ImpactClass
    requires_smoke: bool
    requires_ab: bool
    recommended_action: RecommendedAction
    changed_areas: tuple[ChangedArea, ...] = ()
    capability_diff: CapabilityDiff = Field(default_factory=CapabilityDiff)
    gpu_uuids: tuple[NonEmptyStr, ...] = ()
    reasons: tuple[NonEmptyStr, ...] = ()
    policy_version: NonEmptyStr = IMPACT_POLICY_VERSION
    created_at: AwareTimestamp = Field(default_factory=utcnow)

    @field_validator("gpu_uuids")
    @classmethod
    def _unique_gpus(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("gpu_uuids must be unique")
        return value


def assess_release_impact(
    release: ReleaseMetadata,
    *,
    worker_id: str,
    model_id: str | None,
    model: ModelArtifact | None,
    current_manifest: EngineCapabilityManifest | None,
    inventory_snapshot_revision: int = 0,
    inventory_digest: str | None = None,
    inventory_fresh: bool = True,
    gpu_uuids: tuple[str, ...] = (),
) -> ImpactAssessment:
    """Classify applicability without asserting that a release is an upgrade."""

    reasons: list[str] = []
    current_engine = current_manifest.engine if current_manifest is not None else None
    candidate_sha = release.candidate_executable_sha256
    capability_diff = CapabilityDiff.between(current_manifest, release.capability_manifest)
    impact, areas = classify_release_impact(release)
    applicable = True
    recommended = (
        RecommendedAction.TARGETED_RERUN if impact is ImpactClass.P0 else RecommendedAction.SMOKE_TEST
    )

    if not inventory_fresh:
        reasons.append("STALE_INVENTORY_SNAPSHOT")
    if not release.changed_paths and not release.changed_areas:
        reasons.append("CHANGED_PATHS_NOT_PROVIDED")
    if ChangedArea.UNKNOWN in areas:
        reasons.append("IMPACT_UNCERTAIN_REQUIRES_SMOKE")
    if current_engine is None:
        applicable = False
        impact = ImpactClass.P2
        recommended = RecommendedAction.IGNORE
        reasons.append("CURRENT_ENGINE_NOT_OBSERVED")
    elif current_engine.engine_id != release.engine_id:
        applicable = False
        impact = ImpactClass.P2
        recommended = RecommendedAction.IGNORE
        reasons.append("RELEASE_ENGINE_NOT_INSTALLED")
    elif _already_installed(current_engine, release):
        applicable = False
        impact = ImpactClass.P2
        recommended = RecommendedAction.IGNORE
        reasons.append("RELEASE_ALREADY_INSTALLED")
    else:
        if release.affected_model_families:
            family = _model_family(model)
            if model is None:
                reasons.append("MODEL_NOT_SELECTED_FOR_ASSESSMENT")
            elif family is None:
                reasons.append("MODEL_FAMILY_UNKNOWN")
            elif family not in {item.lower() for item in release.affected_model_families}:
                applicable = False
                impact = ImpactClass.P2
                recommended = RecommendedAction.IGNORE
                reasons.append("AFFECTED_MODEL_FAMILY_NOT_INSTALLED")
            else:
                reasons.append(f"AFFECTS_MODEL_FAMILY:{family}")
        if current_manifest is not None and release.capability_manifest is not None:
            reasons.append("CAPABILITY_SCHEMA_COMPARED")
        if capability_diff.has_changes:
            impact = stronger_impact(impact, capability_diff.impact_class)
            reasons.append(f"CAPABILITY_SCHEMA_CHANGED:{capability_diff.impact_class.value}")
        if candidate_sha is None:
            reasons.append("RELEASE_ARTIFACT_HASH_NOT_SUPPLIED")
        if inventory_fresh and impact is ImpactClass.P0:
            recommended = RecommendedAction.TARGETED_RERUN
        elif inventory_fresh and impact is ImpactClass.P1:
            recommended = RecommendedAction.SMOKE_TEST
        elif impact is ImpactClass.P2:
            recommended = RecommendedAction.IGNORE
        if impact is ImpactClass.P0:
            reasons.append("P0_RELEASE_AREA")
        elif impact is ImpactClass.P1:
            reasons.append("P1_RELEASE_AREA")

    if not inventory_fresh and applicable and impact is ImpactClass.P2:
        # A stale current identity is not enough to dismiss a release. Keep the
        # smoke requirement even when path metadata looks documentation-only.
        impact = ImpactClass.P1
        recommended = RecommendedAction.SMOKE_TEST
        reasons.append("STALE_IDENTITY_REQUIRES_SMOKE")

    requires_smoke = applicable and impact in (ImpactClass.P0, ImpactClass.P1)
    requires_ab = applicable and impact in (ImpactClass.P0, ImpactClass.P1)
    if not applicable:
        recommended = RecommendedAction.IGNORE

    assessment_id = stable_id(
        "impact",
        release.notice_id,
        worker_id,
        model_id or "",
        model.artifact_digest if model is not None else "",
        current_engine.executable_sha256 if current_engine is not None else "",
        inventory_snapshot_revision,
        inventory_fresh,
        IMPACT_POLICY_VERSION,
    )
    return ImpactAssessment(
        assessment_id=assessment_id,
        notice_id=release.notice_id,
        worker_id=worker_id,
        model_id=model_id,
        model_digest=model.artifact_digest if model is not None else None,
        model_identity_complete=model.hashes_complete() if model is not None else False,
        engine_id=release.engine_id,
        current_engine=current_engine,
        candidate_engine_sha256=candidate_sha,
        inventory_snapshot_revision=inventory_snapshot_revision,
        inventory_digest=inventory_digest,
        inventory_fresh=inventory_fresh,
        applicable=applicable,
        impact=impact,
        requires_smoke=requires_smoke,
        requires_ab=requires_ab,
        recommended_action=recommended,
        changed_areas=areas,
        capability_diff=capability_diff,
        gpu_uuids=gpu_uuids,
        reasons=tuple(dict.fromkeys(reasons)),
        policy_version=IMPACT_POLICY_VERSION,
    )


def _model_family(model: ModelArtifact | None) -> str | None:
    if model is None:
        return None
    value = model.model_family or model.architecture
    return value.strip().lower() if value else None


def _already_installed(current: EngineIdentity, release: ReleaseMetadata) -> bool:
    if current.version != release.version or current.build != release.build:
        return False
    if release.source_commit is not None and current.source_commit != release.source_commit:
        return False
    candidate_sha = release.candidate_executable_sha256
    return candidate_sha is None or current.executable_sha256 == candidate_sha
