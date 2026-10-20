"""Deterministic simulated inventory built from Phase 0 fixtures.

This module reads only local fixture text. It does not launch an engine and it
marks the snapshot as simulated, so no simulated result can become a
validated production recipe.
"""

from __future__ import annotations

import platform
import socket
from pathlib import Path

from lab_core.ids import sha256_text, stable_id

from lab_adapters import LlamaCppAdapter
from lab_core import (
    Backend,
    BinaryKind,
    EngineCapabilityManifest,
    EngineId,
    GPUDevice,
    HardwareSnapshot,
    ModelArtifact,
    ModelFile,
    ProcessOutput,
    RegisteredBinary,
    WorkerHealth,
    WorkerSnapshot,
    utcnow,
)

from .config import WorkerSettings


def _fixture_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "fixtures" / "engines" / "llamacpp-0.7.0-dev-build701"
        if candidate.is_dir():
            return candidate
    return None


def _read(path: Path, fallback: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return fallback


_FALLBACK_VERSION = (
    "version: 0.7.0-dev (build 701, commit dd002b91f)\nbuilt with GNU 15.2.0 for Linux x86_64\n"
)
_FALLBACK_HELP = (
    "-m, --model FNAME\n-c, --ctx-size N\n-ngl, --n-gpu-layers N\n"
    "-t, --threads N\n-b, --batch-size N\n-ub, --ubatch-size N\n"
    "-fa, --flash-attn [on|off|auto]\n"
)


def build_llamacpp_manifest(settings: WorkerSettings) -> EngineCapabilityManifest:
    root = _fixture_root()
    if root is not None:
        version_text = _read(root / "version.txt", "") + "\n" + _read(root / "server-version.txt", "")
        help_text = _read(root / "server-help.txt", "") + "\n" + _read(root / "bench-help.txt", "")
    else:
        version_text = _FALLBACK_VERSION
        help_text = _FALLBACK_HELP
    binary_sha = sha256_text("phase1-simulated-llamacpp|" + version_text + "|" + help_text)
    binary = RegisteredBinary(
        executable_id="llama-server",
        engine_id=EngineId.LLAMACPP,
        kind=BinaryKind.SERVER,
        path=settings.engine_path,
        sha256=binary_sha,
        version="0.7.0-dev",
        build="701",
        backend=Backend.CUDA,
    )
    outputs = (
        ProcessOutput(command_id="probe-version", exit_code=0, stdout=version_text),
        ProcessOutput(command_id="probe-help", exit_code=0, stdout=help_text),
    )
    manifest = LlamaCppAdapter().parse_probe_output(outputs, binary)
    engine = manifest.engine.model_copy(update={"executable_path": settings.engine_path})
    return manifest.model_copy(
        update={
            "engine": engine,
            "notes": (
                *manifest.notes,
                "SIMULATED_INVENTORY: parsed from sanitized Phase 0 fixtures, not a live probe.",
            ),
        }
    )


def build_hardware(settings: WorkerSettings) -> HardwareSnapshot:
    uname = platform.uname()
    cpu = platform.processor() or "simulated x86_64 CPU"
    return HardwareSnapshot(
        hostname=socket.gethostname() or "sim-host",
        os=f"{uname.system} {uname.release}",
        kernel=uname.release,
        cpu_model=cpu[:200],
        cpu_threads=16,
        ram_total_bytes=64 * 1024**3,
        ram_available_bytes=48 * 1024**3,
        gpus=(
            GPUDevice(
                uuid="sim-GPU-0",
                index=0,
                name="NVIDIA GeForce RTX 3060 (simulated)",
                vram_total_bytes=12 * 1024**3,
                driver_version="580.0",
                compute_capability="8.6",
                pci_bus_id="sim:00:01.0",
                owned_by_lab=True,
            ),
        ),
        cuda_driver_version="580.0",
        cuda_runtime_version="12.8",
        collected_at=utcnow(),
        contamination_warnings=("PHASE_1_SIMULATED_HARDWARE",),
    )


def build_model(settings: WorkerSettings) -> ModelArtifact:
    return ModelArtifact(
        model_id=settings.model_id,
        display_name=settings.model_id,
        architecture="qwen2",
        model_family="qwen2",
        quantization="Q4_K_M",
        files=(
            ModelFile(
                path=settings.model_path,
                sha256=sha256_text("phase1-simulated-model|" + settings.model_id),
                size_bytes=settings.model_size_bytes,
                verified=True,
            ),
        ),
        path_map=(settings.model_path,),
        tokenizer_id="qwen2",
        metadata_context_tokens=settings.model_context_tokens,
        size_bytes=settings.model_size_bytes,
        verified=True,
        compatible_engines=(EngineId.LLAMACPP,),
        metadata={"simulated": True},
    )


def build_snapshot(settings: WorkerSettings, revision: int) -> WorkerSnapshot:
    now = utcnow()
    return WorkerSnapshot(
        snapshot_id=stable_id("snap", settings.worker_id, revision),
        worker_id=settings.worker_id,
        revision=revision,
        created_at=now,
        hardware=build_hardware(settings),
        engines=(build_llamacpp_manifest(settings),),
        models=(build_model(settings),),
        health=WorkerHealth(
            status="online",
            last_heartbeat_at=now,
            isolated=True,
            warnings=("PHASE_1_SIMULATED_EXECUTION",),
        ),
        notes=("SIMULATED snapshot: no live engine process was launched.",),
    )
