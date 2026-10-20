"""Observed engine discovery and trusted binary registration.

Only configured paths are probed. The worker records the executable digest and
the exact help/version bytes before any adapter is allowed to plan execution.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from lab_adapters import InferenceAdapter
from lab_adapters import registry as adapter_registry
from lab_core import (
    Backend,
    BinaryKind,
    EngineCapabilityManifest,
    EngineId,
    ProcessOutput,
    RegisteredBinary,
)

from .config import WorkerSettings


class EngineDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class EngineBundle:
    engine_id: EngineId
    manifest: EngineCapabilityManifest
    adapter: InferenceAdapter
    binaries: dict[str, RegisteredBinary]
    server_binary: RegisteredBinary | None
    bench_binary: RegisteredBinary | None
    server_script: Path | None = None
    server_script_sha256: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _probe(
    path: Path,
    *,
    args: tuple[str, ...],
    command_id: str,
    settings: WorkerSettings,
    env_extra: dict[str, str] | None = None,
) -> ProcessOutput:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(settings.resolved_state_root),
        "LC_ALL": "C",
        "LANG": "C",
    }
    if env_extra:
        env.update(env_extra)
    try:
        completed = subprocess.run(
            (str(path), *args),
            cwd="/",
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.probe_timeout_seconds,
        )
        return ProcessOutput(
            command_id=command_id,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return ProcessOutput(
            command_id=command_id,
            exit_code=124,
            stdout=(exc.stdout or b"").decode("utf-8", "replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or ""),
            stderr="probe timed out",
            timed_out=True,
        )
    except OSError as exc:
        return ProcessOutput(
            command_id=command_id,
            exit_code=127,
            stderr=f"{type(exc).__name__}: {exc}",
        )


def _registered(
    settings: WorkerSettings,
    *,
    executable_id: str,
    engine_id: EngineId,
    kind: BinaryKind,
    path: Path,
    backend: Backend,
) -> tuple[RegisteredBinary, str, str]:
    if not path.is_file():
        raise EngineDiscoveryError(f"configured engine binary is missing: {path}")
    if not os.access(path, os.X_OK):
        raise EngineDiscoveryError(f"configured engine binary is not executable: {path}")
    digest = sha256_file(path)
    binary = RegisteredBinary(
        executable_id=executable_id,
        engine_id=engine_id,
        kind=kind,
        path=str(path),
        sha256=digest,
        backend=backend,
    )
    return binary, digest, str(path)


def discover_llamacpp(settings: WorkerSettings) -> EngineBundle:
    server_path = Path(settings.llama_server_path).expanduser()
    bench_path = Path(settings.llama_bench_path).expanduser()
    server, _, _ = _registered(
        settings,
        executable_id="llama-server",
        engine_id=EngineId.LLAMACPP,
        kind=BinaryKind.SERVER,
        path=server_path,
        backend=Backend.CUDA,
    )
    bench, _, _ = _registered(
        settings,
        executable_id="llama-bench",
        engine_id=EngineId.LLAMACPP,
        kind=BinaryKind.MICROBENCH,
        path=bench_path,
        backend=Backend.CUDA,
    )
    env = {"LD_LIBRARY_PATH": settings.llama_lib_dir} if Path(settings.llama_lib_dir).is_dir() else {}
    outputs = (
        _probe(
            server_path,
            args=("--version",),
            command_id="probe-llama-server-version",
            settings=settings,
            env_extra=env,
        ),
        _probe(
            server_path,
            args=("--help",),
            command_id="probe-llama-server-help",
            settings=settings,
            env_extra=env,
        ),
        _probe(
            bench_path,
            args=("--version",),
            command_id="probe-llama-bench-version",
            settings=settings,
            env_extra=env,
        ),
        _probe(
            bench_path,
            args=("--help",),
            command_id="probe-llama-bench-help",
            settings=settings,
            env_extra=env,
        ),
    )
    adapter = adapter_registry().get(EngineId.LLAMACPP)
    manifest = adapter.parse_probe_output(outputs, server)
    manifest = manifest.model_copy(
        update={
            "engine": manifest.engine.model_copy(update={"executable_path": str(server_path)}),
            "notes": (*manifest.notes, f"llama-bench={bench_path}", "observed on the local installed build"),
        }
    )
    return EngineBundle(
        engine_id=EngineId.LLAMACPP,
        manifest=manifest,
        adapter=adapter,
        binaries={"server": server, "bench": bench},
        server_binary=server,
        bench_binary=bench,
    )


def discover_strata(settings: WorkerSettings) -> EngineBundle:
    binary_path = Path(settings.strata_path).expanduser()
    binary, _, _ = _registered(
        settings,
        executable_id="strata",
        engine_id=EngineId.STRATA,
        kind=BinaryKind.CLI,
        path=binary_path,
        backend=Backend.CUDA,
    )
    outputs = (
        _probe(
            binary_path,
            args=("--version",),
            command_id="probe-strata-version",
            settings=settings,
        ),
        _probe(
            binary_path,
            args=("--help",),
            command_id="probe-strata-help",
            settings=settings,
        ),
    )
    adapter = adapter_registry().get(EngineId.STRATA)
    manifest = adapter.parse_probe_output(outputs, binary)
    warnings: list[str] = []
    python_path = Path(settings.strata_python).expanduser()
    server_script = Path(settings.strata_server_script).expanduser()
    server_binary: RegisteredBinary | None = None
    server_script_sha: str | None = None
    if not python_path.is_file():
        warnings.append(f"STRATA_PYTHON_MISSING:{python_path}")
    if not server_script.is_file():
        warnings.append(f"STRATA_SERVER_SCRIPT_MISSING:{server_script}")
    if python_path.is_file() and server_script.is_file():
        server_binary = RegisteredBinary(
            executable_id="strata-server",
            engine_id=EngineId.STRATA,
            kind=BinaryKind.SERVER_SCRIPT,
            path=str(python_path),
            sha256=sha256_file(python_path),
            version=manifest.engine.version,
            build=manifest.engine.build,
            backend=Backend.CUDA,
        )
        server_script_sha = sha256_file(server_script)
    manifest = manifest.model_copy(
        update={
            "engine": manifest.engine.model_copy(update={"executable_path": str(binary_path)}),
            "notes": (
                *manifest.notes,
                f"server_entrypoint={server_script}",
                "serving lane is a Lab Custom Protocol over the installed OpenAI-compatible server",
                "native calibration commands are absent and are not synthesized",
            ),
        }
    )
    return EngineBundle(
        engine_id=EngineId.STRATA,
        manifest=manifest,
        adapter=adapter,
        binaries={"cli": binary, **({"server": server_binary} if server_binary else {})},
        server_binary=server_binary,
        bench_binary=None,
        server_script=server_script if server_script.is_file() else None,
        server_script_sha256=server_script_sha,
        warnings=tuple(warnings),
    )


def discover_engines(settings: WorkerSettings) -> tuple[tuple[EngineBundle, ...], tuple[str, ...]]:
    bundles: list[EngineBundle] = []
    warnings: list[str] = []
    for engine in settings.supported_engines:
        try:
            if engine == EngineId.LLAMACPP.value:
                bundles.append(discover_llamacpp(settings))
            elif engine == EngineId.STRATA.value:
                bundle = discover_strata(settings)
                bundles.append(bundle)
                warnings.extend(bundle.warnings)
            else:
                warnings.append(f"UNSUPPORTED_ENGINE_CONFIGURED:{engine}")
        except Exception as exc:
            warnings.append(f"ENGINE_DISCOVERY_FAILED:{engine}:{type(exc).__name__}:{str(exc)[:200]}")
    return tuple(bundles), tuple(warnings)


def known_binary_paths(settings: WorkerSettings) -> tuple[str, ...]:
    paths = [
        settings.llama_server_path,
        settings.llama_bench_path,
        settings.strata_path,
        settings.strata_python,
    ]
    return tuple(str(Path(item).expanduser()) for item in paths if item)


def which_path(value: str) -> str | None:
    return shutil.which(value)
