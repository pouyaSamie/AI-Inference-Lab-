"""Offline serving acceptance with a real owned HTTP process and no engine/GPU."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from lab_core.ids import sha256_text
from lab_worker.engines import sha256_file
from lab_worker.gpu import GpuLeaseError
from lab_worker.real_executor import RealExecutor
from pydantic import ValidationError

from lab_core import (
    BinaryKind,
    CandidateSpec,
    CommandSpec,
    EngineId,
    ExecutionStage,
    ModelArtifact,
    ModelFile,
    ReadinessPredicate,
    RecipeChatPayload,
    RegisteredBinary,
    RunRecipePayload,
    ServerExecutionPlan,
    StopRecipePayload,
)
from tests.test_real_worker_units import _settings

SCRIPT = Path(__file__).parent / "fixtures/recipe_http_server.py"


@pytest.fixture(params=["llamacpp", "strata"])
def serving(tmp_path, monkeypatch, request):
    engine_id = request.param
    settings = _settings(tmp_path, worker_id="serving-test")
    model_file = tmp_path / "model.bin"
    model_file.write_bytes(b"offline model fixture")
    model = ModelArtifact(
        model_id="fixture",
        display_name="Offline fixture",
        architecture="fixture",
        verified=True,
        files=(
            ModelFile(
                path=str(model_file),
                sha256=sha256_file(model_file),
                size_bytes=model_file.stat().st_size,
                verified=True,
            ),
        ),
        metadata={"server_script_sha256": sha256_file(SCRIPT)},
    )
    binary = RegisteredBinary(
        executable_id="fixture-server",
        engine_id=EngineId(engine_id),
        kind=BinaryKind.SERVER,
        path=sys.executable,
        sha256=sha256_file(Path(sys.executable)),
    )
    candidate = CandidateSpec(
        study_id="study-fixture",
        experiment_id="exp-fixture",
        trial_number=1,
        engine_id=engine_id,
        engine_sha256=binary.sha256,
        model_digest=model.artifact_digest,
        worker_id=settings.worker_id,
        context=4096,
        workload_digest="a" * 64,
        parameters={"spec": 2, "resident_experts": False, "mmap_experts": True, "ple_io": "direct"},
    )

    class Adapter:
        def validate_candidate(self, *args):
            return ()

        def _profile(self, *args):
            return {}

        def build_server_plan(self, candidate, sandbox, *, binary, model, port):
            return ServerExecutionPlan(
                engine_id=EngineId(engine_id),
                candidate_digest=candidate.semantic_key(),
                sandbox=sandbox,
                port_range_start=port,
                port_range_end=port,
                start=ExecutionStage(
                    name="offline-server",
                    command=CommandSpec(
                        executable_id=binary.executable_id,
                        executable_sha256=binary.sha256,
                        argv=(str(SCRIPT), "--port", str(port)),
                        cwd=sandbox.work_dir,
                        timeout_seconds=10,
                        readiness=ReadinessPredicate(
                            kind="http", target=f"http://127.0.0.1:{port}/health", timeout_seconds=5
                        ),
                    ),
                ),
            )

    bundle = SimpleNamespace(
        manifest=SimpleNamespace(
            engine=SimpleNamespace(executable_sha256=binary.sha256, executable_path=binary.path)
        ),
        adapter=Adapter(),
        server_binary=binary,
        server_script=SCRIPT,
    )
    owner = RealExecutor(settings)
    owner.runner.binaries = {binary.executable_id: binary}
    monkeypatch.setattr(owner, "_bundle", lambda _: bundle)
    monkeypatch.setattr(
        owner,
        "current_snapshot",
        lambda: SimpleNamespace(
            model=lambda _: model, hardware=SimpleNamespace(gpus=[SimpleNamespace(uuid="GPU-fixture")])
        ),
    )
    monkeypatch.setattr("lab_worker.recipe_server.gpu_preflight", lambda *args: (True, ()))
    payload = RunRecipePayload(
        session_id="session-fixture",
        recipe_id="recipe-fixture",
        recipe_digest="b" * 64,
        candidate=candidate,
        model=model,
        gpu_uuid="GPU-fixture",
        profile_sha256=sha256_text("{}\n"),
    )
    try:
        yield owner, payload, model_file, bundle
    finally:
        owner.serving.stop()


def test_owned_server_start_chat_stop_and_stale_stop_are_safe(serving):
    owner, payload, _file, _bundle = serving
    ready = owner.serving.start(payload, "serving-command", lambda: None).session
    assert ready.state == "ready" and ready.port
    assert owner.serving.start(payload, "replay", lambda: None).session == ready
    with pytest.raises(GpuLeaseError):
        owner.leases.acquire((payload.gpu_uuid,), command_id="competing-benchmark")
    answer = owner.serving.chat(
        RecipeChatPayload(
            session_id=ready.session_id, messages=({"role": "user", "content": "Hello"},), max_tokens=16
        ),
        lambda: None,
    )
    assert answer.content == "offline fixture reply"
    assert not owner.serving.stop(StopRecipePayload(session_id="old-session")).stopped
    assert owner.serving.status().state == "ready"
    process = owner.serving.server._process
    assert owner.serving.stop(StopRecipePayload(session_id=ready.session_id)).stopped
    assert process.poll() is not None
    assert owner.serving.status().state == "stopped"
    with owner.leases.acquire((payload.gpu_uuid,), command_id="after-stop"):
        pass


def test_changed_model_is_refused_without_starting_a_process(serving):
    owner, payload, model_file, _bundle = serving
    model_file.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="model file changed"):
        owner.serving.start(payload, "changed-input", lambda: None)
    assert owner.serving.server is None
    assert owner.serving.status().state == "failed"
    assert not owner.leases.active()


def test_long_chat_is_rejected_before_generation_and_shutdown_cleans_up(serving):
    owner, payload, _file, _bundle = serving
    owner.serving.start(payload, "chat-limit", lambda: None)
    with pytest.raises(RuntimeError, match="exceeds the recipe context"):
        owner.serving.chat(
            RecipeChatPayload(
                session_id=payload.session_id,
                messages=({"role": "user", "content": "x" * 4096},),
                max_tokens=16,
            ),
            lambda: None,
        )
    process = owner.serving.server._process
    owner.serving.stop()
    assert process.poll() is not None
    assert not owner.leases.active()


def test_chat_contract_is_bounded():
    with pytest.raises(ValidationError):
        RecipeChatPayload(session_id="session", messages=(), max_tokens=999999)


def test_old_launch_cannot_restart_an_engine_after_worker_relaunch(serving):
    owner, payload, _file, _bundle = serving
    old = payload.model_copy(update={"issued_at": owner.booted_at - timedelta(seconds=1)})
    with pytest.raises(RuntimeError, match="predates the worker restart"):
        owner.serving.start(old, "old-launch", lambda: None)
    assert owner.serving.server is None and not owner.leases.active()


def test_changed_engine_and_busy_gpu_are_refused(serving, monkeypatch, tmp_path):
    owner, payload, _file, bundle = serving
    changed = tmp_path / "changed-engine"
    changed.write_bytes(b"changed executable")
    original = bundle.manifest.engine.executable_path
    bundle.manifest.engine.executable_path = str(changed)
    with pytest.raises(RuntimeError, match="engine executable changed"):
        owner.serving.start(payload, "changed-engine", lambda: None)
    bundle.manifest.engine.executable_path = original
    monkeypatch.setattr("lab_worker.recipe_server.gpu_preflight", lambda *args: (False, ("busy",)))
    with pytest.raises(RuntimeError, match="GPU is busy"):
        owner.serving.start(payload, "busy-gpu", lambda: None)
    assert owner.serving.server is None and not owner.leases.active()


def test_failed_context_smoke_stops_the_owned_process_and_releases_gpu(serving, monkeypatch):
    owner, payload, _file, _bundle = serving
    started = []
    original = owner.runner.start_server

    def start(**kwargs):
        result = original(**kwargs)
        started.append(result[0])
        return result

    monkeypatch.setattr(owner.runner, "start_server", start)
    monkeypatch.setattr("lab_worker.recipe_server.effective_context", lambda _: (2048, {}))
    with pytest.raises(RuntimeError, match="context capacity"):
        owner.serving.start(payload, "wrong-context", lambda: None)
    assert started and started[0]._process.poll() is not None
    assert not owner.leases.active()


def test_stop_during_startup_keeps_gpu_locked_until_the_process_is_stopped(serving, monkeypatch):
    owner, payload, _file, _bundle = serving
    original = owner.runner.start_server
    launched, release = Event(), Event()
    processes = []

    def start(**kwargs):
        result = original(**kwargs)
        processes.append(result[0]._process)
        launched.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(owner.runner, "start_server", start)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owner.serving.start, payload, "cancel-startup", lambda: None)
        try:
            assert launched.wait(5)
            assert not owner.serving.stop(StopRecipePayload(session_id=payload.session_id)).stopped
            with pytest.raises(GpuLeaseError):
                owner.leases.acquire((payload.gpu_uuid,), command_id="too-early")
        finally:
            release.set()
        with pytest.raises(RuntimeError):
            future.result(timeout=5)
    assert processes[0].poll() is not None
    assert owner.serving.status().state == "stopped"
    assert not owner.leases.active()
