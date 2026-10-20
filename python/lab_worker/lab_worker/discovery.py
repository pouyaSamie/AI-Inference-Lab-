"""Composition of a real worker inventory snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lab_core.ids import stable_id

from lab_core import EngineId, ModelArtifact, WorkerHealth, WorkerSnapshot, utcnow

from .config import WorkerSettings
from .engines import EngineBundle, discover_engines
from .hardware import collect_hardware
from .models import discover_models


@dataclass(frozen=True)
class DiscoveryResult:
    snapshot: WorkerSnapshot
    engines: tuple[EngineBundle, ...]
    warnings: tuple[str, ...] = ()
    models_count: int = 0


def _annotate_strata_models(
    models: tuple[ModelArtifact, ...], engines: tuple[EngineBundle, ...]
) -> tuple[ModelArtifact, ...]:
    bundle = next((item for item in engines if item.engine_id is EngineId.STRATA), None)
    if bundle is None:
        return models
    annotated: list[ModelArtifact] = []
    for item in models:
        metadata = dict(item.metadata)
        if metadata.get("model_type") == "strata-pack":
            metadata["engine_executable"] = bundle.manifest.engine.executable_path
            metadata["engine_sha256"] = bundle.manifest.engine.executable_sha256
            if bundle.server_script is not None:
                metadata["server_script"] = str(bundle.server_script)
            if bundle.server_script_sha256 is not None:
                metadata["server_script_sha256"] = bundle.server_script_sha256
        annotated.append(item.model_copy(update={"metadata": metadata}))
    return tuple(annotated)


def discover_snapshot(
    settings: WorkerSettings,
    *,
    revision: int,
    roots: tuple[Path, ...] | None = None,
    active_leases: tuple[str, ...] = (),
    owned_pids: tuple[int, ...] = (),
    include_engines: bool = True,
    include_models: bool = True,
    include_hardware: bool = True,
    hash_models: bool | None = None,
) -> DiscoveryResult:
    settings.ensure_directories()
    warnings: list[str] = []
    engines: tuple[EngineBundle, ...] = ()
    if include_engines:
        engines, engine_warnings = discover_engines(settings)
        warnings.extend(engine_warnings)
        if not engines:
            warnings.append("NO_ENGINE_DISCOVERED")
    else:
        # Keep the previously known manifests out of scope; discovery is
        # intentionally explicit rather than fabricating an empty capability.
        warnings.append("ENGINE_DISCOVERY_SKIPPED")

    models: tuple[ModelArtifact, ...] = ()
    if include_models:
        scanned = discover_models(settings, roots=roots, warnings=warnings, hash_models=hash_models)
        models = _annotate_strata_models(scanned, engines)
        if not models:
            warnings.append("NO_MODEL_DISCOVERED")

    hardware = (
        collect_hardware(settings)
        if include_hardware
        else collect_hardware(settings).model_copy(
            update={"contamination_warnings": ("HARDWARE_DISCOVERY_SKIPPED",)}
        )
    )
    if not hardware.gpus:
        warnings.append("NO_GPU_DISCOVERED")
    health = WorkerHealth(
        status="online",
        last_heartbeat_at=utcnow(),
        active_leases=active_leases,
        owned_pids=owned_pids,
        isolated=True,
        warnings=tuple(dict.fromkeys(warnings)),
    )
    snapshot = WorkerSnapshot(
        snapshot_id=stable_id("snap", settings.worker_id, revision, utcnow().isoformat()),
        worker_id=settings.worker_id,
        revision=max(1, revision),
        created_at=utcnow(),
        hardware=hardware,
        engines=tuple(bundle.manifest for bundle in engines),
        models=tuple(models),
        health=health,
        notes=(
            "REAL_INVENTORY: executable digests and model file digests are observed on this host.",
            "No engine or model file was modified by discovery.",
        ),
    )
    return DiscoveryResult(
        snapshot=snapshot,
        engines=engines,
        warnings=tuple(dict.fromkeys(warnings)),
        models_count=len(snapshot.models),
    )
