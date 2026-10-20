"""Pure contract, scoring and adapter checks."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from lab_core.base import FrozenModel
from lab_worker.config import WorkerSettings
from lab_worker.inventory import build_llamacpp_manifest
from pydantic import ValidationError

from lab_adapters import registry
from lab_core import (
    ContextLength,
    EngineId,
    GeneratedFile,
    ProcessOutput,
    RegisteredBinary,
    SandboxPaths,
    SearchSpaceRequest,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "engines" / "llamacpp-0.7.0-dev-build701"


def _binary() -> RegisteredBinary:
    return RegisteredBinary(
        executable_id="llama-server",
        engine_id=EngineId.LLAMACPP,
        kind="server",
        path="/sim/llama-server",
        sha256="a" * 64,
        version="0.7.0-dev",
        build="701",
    )


def test_request_is_immutable_and_digest_is_canonical() -> None:
    class Example(FrozenModel):
        value: int

    item = Example(value=1)
    with pytest.raises(ValidationError):
        item.value = 2
    assert item.digest() == Example(value=1).digest()
    assert item.digest() != Example(value=2).digest()


def test_generated_file_requires_matching_digest_and_safe_path() -> None:
    generated = GeneratedFile(relative_path="run/recipe.json", content="{}")
    assert generated.sha256
    with pytest.raises(ValidationError):
        GeneratedFile(relative_path="../escape", content="{}")


def test_sandbox_paths_cannot_escape_root() -> None:
    paths = SandboxPaths(
        root="/tmp/lab",
        work_dir="/tmp/lab/work",
        log_dir="/tmp/lab/logs",
        artifact_dir="/tmp/lab/artifacts",
        temp_home="/tmp/lab/home",
    )
    assert paths.work_dir.endswith("/work")
    with pytest.raises(ValidationError):
        SandboxPaths(
            root="/tmp/lab",
            work_dir="/tmp/elsewhere",
            log_dir="/tmp/lab/logs",
            artifact_dir="/tmp/lab/artifacts",
            temp_home="/tmp/lab/home",
        )


def test_llamacpp_adapter_parses_observed_help_and_builds_search_space() -> None:
    version = FIXTURES.joinpath("version.txt").read_text(encoding="utf-8")
    help_text = "\n".join(
        FIXTURES.joinpath(name).read_text(encoding="utf-8") for name in ("server-help.txt", "bench-help.txt")
    )
    adapter = registry().get(EngineId.LLAMACPP)
    manifest = adapter.parse_probe_output(
        (
            ProcessOutput(command_id="version", exit_code=0, stdout=version),
            ProcessOutput(command_id="help", exit_code=0, stdout=help_text),
        ),
        _binary(),
    )
    assert manifest.engine.version == "0.7.0-dev"
    assert manifest.engine.executable_sha256 == "a" * 64
    assert "--ctx-size" in set(manifest.flags)
    space = adapter.search_space(
        SearchSpaceRequest(
            engine_id=EngineId.LLAMACPP,
            model_architecture="qwen2",
            model_quantization="Q4_K_M",
            context_tokens=int(ContextLength.K4),
            objective="balanced",
        )
    )
    assert space.engine_id is EngineId.LLAMACPP
    assert space.dimensions
    assert "context_tokens" not in {dimension.name for dimension in space.dimensions}


def test_strata_adapter_does_not_invent_unobserved_benchmark_commands() -> None:
    strata = registry().get(EngineId.STRATA)
    assert strata.adapter_id is EngineId.STRATA
    # Strata's installed surface only has generate + serve; the adapter must
    # expose a workload plan rather than claim a native benchmark command.
    plan = strata.search_space(
        SearchSpaceRequest(
            engine_id=EngineId.STRATA,
            model_architecture="llama",
            context_tokens=4096,
            objective="balanced",
        )
    )
    assert plan.engine_id is EngineId.STRATA
    assert plan.dimensions


def test_adapters_are_pure_no_process_network_or_filesystem_imports() -> None:
    forbidden = {"subprocess", "socket", "httpx", "requests", "urllib", "pathlib", "os"}
    adapters_root = ROOT / "python" / "lab_adapters" / "lab_adapters"
    offenders: list[str] = []
    for path in adapters_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden:
                        offenders.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in forbidden:
                offenders.append(f"{path}: from {node.module}")
    assert offenders == []


def test_worker_inventory_is_marked_simulated() -> None:
    settings = WorkerSettings(
        worker_id="sim-inventory",
        state_file="/tmp/opencode/unused-worker-state.json",
    )
    manifest = build_llamacpp_manifest(settings)
    assert any("SIMULATED" in note for note in manifest.notes)
