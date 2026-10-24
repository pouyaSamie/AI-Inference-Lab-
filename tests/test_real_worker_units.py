"""Unit coverage for the real worker's local building blocks.

These tests never download weights, launch an inference engine, or require a
GPU. They use a tiny synthetic GGUF file and a trusted Python interpreter to
exercise the same process, lease and journal paths the real worker uses.
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Thread

import pytest
from lab_worker.config import WorkerSettings
from lab_worker.engines import sha256_file
from lab_worker.gpu import GpuLeaseError, GpuLeaseManager
from lab_worker.hardware import process_is_alive, process_start_ticks
from lab_worker.journal import WorkerJournal
from lab_worker.models import HashCache, discover_models, read_gguf_metadata
from lab_worker.runner import ProcessRunner
from lab_worker.sandbox import create_sandbox

from lab_core import Backend, BinaryKind, CommandSpec, EngineId, ReadinessPredicate, RegisteredBinary


def _gguf_value(value: object) -> bytes:
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return struct.pack("<I", 8) + struct.pack("<Q", len(encoded)) + encoded
    if isinstance(value, int):
        return struct.pack("<I", 4) + struct.pack("<I", value)
    raise TypeError(type(value))


def write_gguf(path: Path, values: dict[str, object]) -> None:
    body = bytearray(b"GGUF")
    body += struct.pack("<I", 3)
    body += struct.pack("<Q", 0)
    body += struct.pack("<Q", len(values))
    for key, value in values.items():
        encoded = key.encode("utf-8")
        body += struct.pack("<Q", len(encoded)) + encoded
        body += _gguf_value(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(body))


def _settings(tmp_path: Path, **updates: object) -> WorkerSettings:
    values: dict[str, object] = {
        "state_root": str(tmp_path / "state"),
        "state_file": str(tmp_path / "state" / "worker.json"),
        "model_roots": [str(tmp_path / "models")],
        "llama_lib_dir": str(tmp_path / "no-lib"),
        "telemetry_interval_ms": 100,
        "command_grace_seconds": 2,
        "lease_renew_seconds": 5,
    }
    values.update(updates)
    settings = WorkerSettings.model_validate(values)
    settings.ensure_directories()
    return settings


def test_gguf_metadata_and_shard_grouping(tmp_path: Path) -> None:
    model_root = tmp_path / "models"
    write_gguf(
        model_root / "Org" / "Tiny-00001-of-00002.gguf",
        {
            "general.architecture": "qwen2",
            "general.name": "Tiny Test",
            "qwen2.context_length": 8192,
            "qwen2.parameter_count": 42,
        },
    )
    write_gguf(
        model_root / "Org" / "Tiny-00002-of-00002.gguf",
        {"general.architecture": "qwen2", "general.name": "Tiny Test"},
    )
    metadata = read_gguf_metadata(model_root / "Org" / "Tiny-00001-of-00002.gguf")
    assert metadata.architecture == "qwen2"
    assert metadata.context_length == 8192
    assert metadata.parameter_count == 42

    settings = _settings(tmp_path)
    warnings: list[str] = []
    models = discover_models(
        settings,
        roots=(model_root,),
        warnings=warnings,
        hash_models=True,
    )
    assert len(models) == 1
    model = models[0]
    assert model.metadata_context_tokens == 8192
    assert len(model.files) == 2
    assert model.files[0].shard_index == 1
    assert model.files[1].shard_count == 2
    assert model.verified is True
    assert all(item.sha256 for item in model.files)
    assert warnings == []


def test_strata_pack_resolves_read_only_native_shards(tmp_path: Path) -> None:
    model_root = tmp_path / "models"
    source = model_root / "Strata-Tiny" / "models" / "Q2_0" / "Tiny-00001-of-00002.gguf"
    source_second = model_root / "Strata-Tiny" / "models" / "Q2_0" / "Tiny-00002-of-00002.gguf"
    write_gguf(
        source,
        {
            "general.architecture": "qwen2",
            "general.name": "Strata Tiny",
            "qwen2.context_length": 4096,
        },
    )
    write_gguf(
        source_second,
        {"general.architecture": "qwen2", "general.name": "Strata Tiny"},
    )
    pack = model_root / "Strata-Tiny" / "packs" / "q2_0"
    pack.mkdir(parents=True)
    (pack / "index.txt").write_text("# synthetic pack\n", encoding="utf-8")
    (pack / "native_experts.txt").write_text("# synthetic native experts\n", encoding="utf-8")
    (pack / "dense.bin").write_bytes(b"dense")
    (pack / "experts.bin").write_bytes(b"experts")
    (pack / "conversions.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "source_shards": [
                    {"name": source.name, "size": source.stat().st_size},
                    {"name": source_second.name, "size": source_second.stat().st_size},
                ],
            }
        ),
        encoding="utf-8",
    )

    settings = _settings(tmp_path)
    warnings: list[str] = []
    models = discover_models(settings, roots=(model_root,), warnings=warnings, hash_models=True)
    strata = [model for model in models if model.model_family == "strata"]
    assert len(strata) == 1
    model = strata[0]
    assert model.metadata["native_shard"] == str(source)
    assert model.metadata["native_shard_size_bytes"] == source.stat().st_size
    first_shard = next(item for item in model.files if item.shard_index == 1)
    assert model.metadata["native_shard_sha256"] == first_shard.sha256
    assert model.metadata["source_shards"] == [
        {"name": source.name, "size": source.stat().st_size},
        {"name": source_second.name, "size": source_second.stat().st_size},
    ]
    source_files = [item for item in model.files if item.shard_index is not None]
    assert [item.path for item in source_files] == [str(source), str(source_second)]
    assert all(item.shard_count == 2 and item.verified for item in source_files)
    assert model.verified is True
    assert warnings == []

    (pack / "conversions.json").write_text("not json", encoding="utf-8")
    warnings.clear()
    models = discover_models(settings, roots=(model_root,), warnings=warnings, hash_models=False)
    strata = [model for model in models if model.model_family == "strata"]
    assert strata and strata[0].metadata["native_shard"] is None
    assert any(item.startswith("STRATA_SOURCE_SHARDS_MISSING") for item in warnings)


def test_hash_cache_reuses_stat_identity(tmp_path: Path) -> None:
    path = tmp_path / "weights.gguf"
    path.write_bytes(b"GGUF" + b"\x00" * 64)
    cache_path = tmp_path / "cache.json"
    first = HashCache(cache_path)
    digest = first.digest(path)
    first.flush()
    second = HashCache(cache_path)
    assert second.digest(path) == digest
    path.write_bytes(path.read_bytes() + b"changed")
    changed = second.digest(path)
    assert changed.sha256 != digest.sha256
    assert changed.size_bytes != digest.size_bytes


def test_gpu_lease_is_exclusive_per_uuid(tmp_path: Path) -> None:
    uuid = "GPU-078cc33c-e5cb-0cb2-2ac3-95f087497407"
    first = GpuLeaseManager(tmp_path / "leases", "worker-a")
    second = GpuLeaseManager(tmp_path / "leases", "worker-a")
    lease = first.acquire((uuid,), command_id="command-1")
    try:
        assert first.active() == (uuid,)
        with pytest.raises(GpuLeaseError, match="already leased"):
            second.acquire((uuid,), command_id="command-2")
    finally:
        lease.release()
    replacement = second.acquire((uuid,), command_id="command-3")
    replacement.release()
    with pytest.raises(GpuLeaseError, match="unsafe GPU UUID"):
        first.acquire(("../../etc/passwd",), command_id="bad")


def _python_binary() -> RegisteredBinary:
    python = Path(sys.executable).resolve()
    return RegisteredBinary(
        executable_id="test-python",
        engine_id=EngineId.LLAMACPP,
        kind=BinaryKind.CLI,
        path=str(python),
        sha256=sha256_file(python),
        backend=Backend.CPU,
    )


def _command(binary: RegisteredBinary, sandbox, argv: tuple[str, ...], timeout: int = 10) -> CommandSpec:
    return CommandSpec(
        executable_id=binary.executable_id,
        executable_sha256=binary.sha256,
        argv=argv,
        cwd=sandbox.work_dir,
        timeout_seconds=timeout,
        readiness=ReadinessPredicate(),
    )


def test_runner_success_timeout_and_cancellation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    journal = WorkerJournal(settings.resolved_journal_root, settings.worker_id)
    binary = _python_binary()
    runner = ProcessRunner(settings, binaries={binary.executable_id: binary}, journal=journal)
    sandbox = create_sandbox(settings, "runner-test")

    success = runner.run_to_completion(
        command_id="success",
        stage="test",
        command=_command(binary, sandbox, ("-c", "print('hello from worker')")),
        sandbox=sandbox,
    )
    assert success.succeeded, success.error
    assert "hello from worker" in success.stdout_text()
    assert success.artifacts

    timed_out = runner.run_to_completion(
        command_id="timeout",
        stage="test",
        command=_command(binary, sandbox, ("-c", "import time; time.sleep(30)"), timeout=1),
        sandbox=sandbox,
    )
    assert timed_out.timed_out is True
    assert not timed_out.succeeded
    assert timed_out.exit_code is not None

    cancel = Event()
    holder: dict[str, object] = {}

    def run() -> None:
        holder["result"] = runner.run_to_completion(
            command_id="cancel",
            stage="test",
            command=_command(binary, sandbox, ("-c", "import time; time.sleep(30)")),
            sandbox=sandbox,
            cancel_event=cancel,
        )

    thread = Thread(target=run, daemon=True)
    thread.start()
    time.sleep(0.3)
    cancel.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    cancelled = holder["result"]
    assert cancelled.cancelled is True
    assert cancelled.exit_code is not None


def test_journal_recovers_only_owned_process_group(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    journal = WorkerJournal(settings.resolved_journal_root, settings.worker_id)
    proc = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(30)"),
        start_new_session=True,
    )
    try:
        journal.process_started(
            command_id="orphan",
            pid=proc.pid,
            pgid=proc.pid,
            start_ticks=process_start_ticks(proc.pid),
            executable=sys.executable,
            argv=(sys.executable, "-c", "import time; time.sleep(30)"),
            gpu_uuids=(),
            log_path=str(tmp_path / "orphan.log"),
        )
        assert process_is_alive(proc.pid)
        killed = journal.recover_owned_processes()
        assert killed == (proc.pid,)
        proc.wait(timeout=5)
        assert not process_is_alive(proc.pid)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def _write_probe_script(path: Path, version: str, flags: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    help_text = "\n".join(f"  {flag} value" for flag in ("--model", *flags))
    path.write_text(
        f"""#!{sys.executable}
import sys

if "--version" in sys.argv:
    print({version!r})
else:
    print({help_text!r})
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_engine_discovery_uses_only_configured_probe_paths(tmp_path: Path) -> None:
    from lab_worker.engines import discover_llamacpp

    version = "version: 0.7.0-dev (build 701, commit dd002b91f)\nbuilt with GNU 15.2.0 for Linux x86_64"
    server = tmp_path / "bin" / "llama-server"
    bench = tmp_path / "bin" / "llama-bench"
    flags = (
        "--ctx-size",
        "--n-gpu-layers",
        "--threads",
        "--batch-size",
        "--ubatch-size",
        "--flash-attn",
        "--cache-type-k",
        "--cache-type-v",
        "--host",
        "--port",
        "--alias",
        "--repetitions",
        "--n-prompt",
        "--n-gen",
        "--n-depth",
        "--output",
    )
    _write_probe_script(server, version, flags)
    _write_probe_script(bench, version, flags)
    settings = _settings(
        tmp_path,
        llama_server_path=str(server),
        llama_bench_path=str(bench),
        supported_engines=["llamacpp"],
    )
    bundle = discover_llamacpp(settings)
    assert bundle.manifest.engine.version == "0.7.0-dev"
    assert bundle.manifest.engine.build == "701"
    assert bundle.manifest.engine.source_commit == "dd002b91f"
    assert bundle.manifest.engine.executable_sha256 == sha256_file(server)
    assert bundle.server_binary is not None
    assert bundle.bench_binary is not None
    assert {item.key for item in bundle.manifest.descriptors} >= {"--ctx-size", "--port"}

    # Connect actual discovery output to the real executor/runner. Role keys
    # like "server" must never become executable registry identities.
    from dataclasses import replace

    from lab_worker.discovery import DiscoveryResult
    from lab_worker.inventory import build_snapshot
    from lab_worker.real_executor import RealExecutionError, RealExecutor
    from lab_worker.runner import ExecutableTrustError

    second = replace(
        bundle,
        binaries={
            "server": bundle.server_binary.model_copy(
                update={"executable_id": "strata-server", "engine_id": EngineId.STRATA}
            )
        },
    )
    discovery = DiscoveryResult(snapshot=build_snapshot(settings, 1), engines=(bundle, second))
    executor = RealExecutor(settings, discovery=discovery)
    sandbox = create_sandbox(settings, "registry-regression")
    for binary in (*bundle.binaries.values(), *second.binaries.values()):
        assert executor.runner.resolve_binary(_command(binary, sandbox, ("--help",))) == binary
    conflicting = replace(
        bundle, binaries={"server": bundle.server_binary.model_copy(update={"sha256": "f" * 64})}
    )
    with pytest.raises(RealExecutionError, match="conflicting executable registration"):
        RealExecutor(settings, discovery=replace(discovery, engines=(bundle, conflicting)))
    server.write_text("#!/bin/sh\nexit 0\n")
    with pytest.raises(ExecutableTrustError, match="changed"):
        executor.runner.resolve_binary(_command(bundle.server_binary, sandbox, ("--help",)))


def test_gguf_folder_name_does_not_hide_models_and_sidecars_are_excluded(tmp_path: Path) -> None:
    root = tmp_path / "models"
    folder = root / "Strata-Qwen" / "models/Q2_0"
    write_gguf(folder / "Qwen-00001-of-00002.gguf", {"general.architecture": "qwen2"})
    write_gguf(folder / "Qwen-00002-of-00002.gguf", {"general.architecture": "qwen2"})
    write_gguf(root / "mmproj-F32.gguf", {"general.architecture": "clip"})
    write_gguf(root / "mtp-q2_0.gguf", {"general.architecture": "mtp"})
    (folder / "Qwen-00001-of-00002.gguf.done").write_text("done")
    settings = _settings(tmp_path)
    models = discover_models(settings, roots=(root,), hash_models=False)
    assert len(models) == 1
    assert len(models[0].files) == 2
    assert not models[0].verified
    assert all(item.sha256 is None for item in models[0].files)


def test_selected_hashing_progress_and_metadata_scan_preserve_cache(tmp_path: Path) -> None:
    import json

    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"first model")
    second.write_bytes(b"second model")
    cache = HashCache(
        tmp_path / "cache/hash-cache.json",
        hash_paths=frozenset([str(first)]),
        progress=True,
        model_id="first-model",
    )
    assert cache.model_digest(first, True) is not None
    assert cache.model_digest(second, True) is None
    cache.report("complete", force=True)
    progress = json.loads((tmp_path / "cache/verification-progress.json").read_text())
    assert progress["bytes_done"] == progress["bytes_total"] == len(b"first model")
    assert progress["files_done"] == progress["files_total"] == 1
    assert progress["model_id"] == "first-model"
    reopened = HashCache(tmp_path / "cache/hash-cache.json")
    assert reopened.model_digest(first, False) is not None
    first.write_bytes(b"changed")
    assert reopened.model_digest(first, False) is None
    assert second.read_bytes() == b"second model"


def test_model_hashing_can_stop_without_caching_partial_identity(tmp_path: Path) -> None:
    from lab_worker.models import ModelVerificationCancelled

    model = tmp_path / "model.bin"
    model.write_bytes(b"never a partial qualifying identity")
    calls = 0

    def cancelled() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    cache = HashCache(tmp_path / "hash-cache.json", cancelled=cancelled)
    with pytest.raises(ModelVerificationCancelled):
        cache.digest(model)
    assert cache.lookup(model) is None
    assert not (tmp_path / "hash-cache.json").exists()


def test_verified_discovery_survives_restart_and_invalidates_changed_files(tmp_path, monkeypatch):
    root = tmp_path / "models"
    model = root / "Tiny.gguf"
    write_gguf(model, {"general.architecture": "qwen2", "general.name": "Tiny"})
    settings = _settings(tmp_path)
    first = discover_models(settings, hash_models=True)
    assert first[0].verified
    # A new cache/discovery object must not rehash unchanged files at startup.
    monkeypatch.setattr(HashCache, "digest", lambda *_: pytest.fail("unexpected startup rehash"))
    reused = discover_models(settings, hash_models=False)
    assert reused[0].verified and reused[0].artifact_digest == first[0].artifact_digest
    monkeypatch.setattr("lab_worker.models.os.access", lambda *_: False)
    assert not discover_models(settings, hash_models=False)[0].verified
    monkeypatch.undo()
    write_gguf(model, {"general.architecture": "qwen2", "general.name": "Changed model"})
    assert not discover_models(settings, hash_models=False)[0].verified
    model.unlink()
    assert not discover_models(settings, hash_models=False)


def test_interrupted_discovery_preserves_finished_files_and_retries(tmp_path):
    from lab_worker.models import ModelVerificationCancelled

    root = tmp_path / "models"
    first, second = root / "First.gguf", root / "Second.gguf"
    for file in (first, second):
        write_gguf(file, {"general.architecture": "qwen2", "general.name": file.stem})
    settings = _settings(tmp_path)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        return calls >= 3  # Before the second file; the first digest is flushed.

    paths = frozenset([str(first), str(second)])
    with pytest.raises(ModelVerificationCancelled):
        discover_models(settings, hash_models=True, hash_paths=paths, cancelled=cancel)
    cache = HashCache(settings.resolved_hash_cache)
    assert cache.lookup(first) is not None
    assert cache.lookup(second) is None
    progress = json.loads(settings.resolved_hash_cache.with_name("verification-progress.json").read_text())
    assert progress["state"] == "failed"
    assert all(model.verified for model in discover_models(settings, hash_models=True, hash_paths=paths))
    assert all(model.verified for model in discover_models(settings, hash_models=False))


@pytest.mark.parametrize(
    "effective,expected,cancel",
    [
        (4096, "feasible", False),
        (2048, "resource_infeasible", False),
        (None, "inconclusive", False),
        (4096, "inconclusive", True),
    ],
)
def test_strata_managed_preflight_uses_owned_server_and_actual_context(
    tmp_path, monkeypatch, effective, expected, cancel
):
    from types import SimpleNamespace

    from lab_adapters.base.parsing import server_readiness
    from lab_worker.real_executor import RealExecutor

    from lab_core import ContextLength, GeneratedFile
    from lab_worker import real_executor

    settings = _settings(tmp_path)
    binary = _python_binary()
    executor = RealExecutor(settings)
    executor.runner.binaries = {binary.executable_id: binary}
    monkeypatch.setattr(real_executor, "gpu_preflight", lambda *_: (True, ()))
    monkeypatch.setattr(
        real_executor.psutil, "virtual_memory", lambda: SimpleNamespace(available=32 * 1024**3)
    )
    pids = []
    start = executor.runner.start_server

    def track(**kwargs):
        assert kwargs["lease"] is not None
        assert kwargs["cancel_event"] is executor._active["test-strata-preflight"]
        server, result = start(**kwargs)
        if server:
            pids.append(server._process.pid)
        if cancel:
            kwargs["cancel_event"].set()
        return server, result

    monkeypatch.setattr(executor.runner, "start_server", track)

    class Adapter:
        def search_space(self, request):
            from lab_adapters.strata.adapter import StrataAdapter

            return StrataAdapter().search_space(request)

        def build_server_plan(self, candidate, sandbox, **kwargs):
            assert candidate.engine_id == "strata"
            assert candidate.context == 4096
            assert candidate.parameters["spec"] >= 2
            assert candidate.parameters["prefill"] == "auto"
            profile = Path(sandbox.work_dir) / "test-profile.json"
            code = (
                "import http.server,json; "
                f"doc=json.load(open({str(profile)!r})); "
                "H=type('H',(http.server.BaseHTTPRequestHandler,),{"
                "'do_GET':lambda s:(s.send_response(200),s.end_headers(),"
                "s.wfile.write(json.dumps(doc).encode())),"
                "'log_message':lambda *a:None}); "
                f"http.server.HTTPServer(('127.0.0.1',{kwargs['port']}),H).serve_forever()"
            )
            command = _command(binary, sandbox, ("-c", code)).model_copy(
                update={"readiness": server_readiness("/health", timeout=5)}
            )
            return SimpleNamespace(
                generated_files=(
                    GeneratedFile(
                        relative_path="test-profile.json", content=json.dumps({"n_ctx": effective})
                    ),
                ),
                start=SimpleNamespace(command=command),
            )

    payload = SimpleNamespace(
        experiment_id="test-strata-preflight", spec_digest="a" * 64, gpu_uuids=("GPU-test",)
    )
    bundle = SimpleNamespace(
        engine_id=EngineId.STRATA,
        server_binary=binary,
        adapter=Adapter(),
        manifest=SimpleNamespace(engine=SimpleNamespace(executable_sha256="a" * 64)),
    )
    model = SimpleNamespace(
        path_map={"fixture": "fixture"},
        artifact_digest="a" * 64,
        model_family="strata",
        quantization="IQ1_M",
        metadata={},
        files=(),
    )
    proof = executor._preflight_allocation(payload, bundle, model, ContextLength(4096))
    assert proof.status.value == expected
    assert pids and all(not process_is_alive(pid) for pid in pids)
    assert executor.leases.active() == ()
    assert executor._active == {}
    if expected == "feasible":
        assert "allocation_gpu_lease=held" in proof.evidence
        assert proof.requires_full_context_proof


def test_strata_preflight_never_launches_when_gpu_is_busy(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from lab_worker.real_executor import RealExecutor

    from lab_core import ContextLength
    from lab_worker import real_executor

    executor = RealExecutor(_settings(tmp_path))
    monkeypatch.setattr(real_executor, "gpu_preflight", lambda *_: (False, ("EXTERNAL_GPU_COMPUTE:foreign",)))

    def unexpected(*_):
        pytest.fail("busy GPU must not start an allocation server")

    monkeypatch.setattr(executor, "_preflight_managed_allocation", unexpected)
    proof = executor._preflight_allocation(
        SimpleNamespace(experiment_id="busy-strata", gpu_uuids=("GPU-test",)),
        SimpleNamespace(engine_id=EngineId.STRATA),
        None,
        ContextLength(4096),
    )
    assert proof.status.value == "inconclusive"
    assert "Retry when it is quiet" in proof.reason
    assert executor.leases.active() == ()
    assert executor._active == {}


@pytest.mark.parametrize(
    "parameters,available_gib,blocked",
    [
        ({}, 64, True),
        ({"mmap_experts": False, "resident_experts": False, "ple_io": "direct"}, 64, True),
        ({"mmap_experts": True, "resident_experts": True, "ple_io": "direct"}, 64, True),
        ({"mmap_experts": True, "resident_experts": False, "ple_io": "ram"}, 64, True),
        ({"mmap_experts": True, "resident_experts": False, "ple_io": "direct"}, 7, True),
        ({"mmap_experts": True, "resident_experts": False, "ple_io": "direct"}, 12, False),
    ],
)
def test_strata_memory_guard_rejects_unsafe_old_plans_and_low_available_ram(
    monkeypatch, parameters, available_gib, blocked
):
    from types import SimpleNamespace

    from lab_core import ModelArtifact, ModelFile
    from lab_worker import real_executor

    monkeypatch.setattr(
        real_executor.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(available=available_gib * 1024**3),
    )
    model = ModelArtifact(
        model_id="test-memory",
        display_name="Test",
        architecture="strata",
        files=(ModelFile(path="/fixture/dense.bin", size_bytes=2 * 1024**3),),
    )
    failure = real_executor._strata_memory_failure(parameters, model)
    assert (failure is not None) is blocked
    if failure:
        assert failure.kind.value == "INSUFFICIENT_RAM"


@pytest.mark.parametrize("family", ["coder-iq1_m", "q2_0"])
def test_strata_shipped_profile_is_discovered_hashed_and_rechecked(tmp_path, monkeypatch, family):
    from types import SimpleNamespace

    from lab_worker.discovery import _annotate_strata_models

    from lab_core import ModelArtifact
    from lab_worker import real_executor

    engine = tmp_path / "engine"
    script = engine / "serve/server.py"
    script.parent.mkdir(parents=True)
    script.write_text("# fixture")
    profile = engine / "data" / ("expert-profile-coder.bin" if "coder" in family else "expert-profile.bin")
    profile.parent.mkdir()
    profile.write_bytes(b"fixture ranked profile")
    bundle = SimpleNamespace(
        engine_id=EngineId.STRATA,
        server_script=script,
        server_script_sha256="a" * 64,
        manifest=SimpleNamespace(
            engine=SimpleNamespace(executable_path="/fixture/strata", executable_sha256="b" * 64)
        ),
    )
    model = ModelArtifact(
        model_id="profile-test",
        display_name="Profile test",
        architecture="strata-pack",
        metadata={"model_type": "strata-pack", "pack_path": f"/models/{family}"},
    )
    observed = _annotate_strata_models((model,), (bundle,))[0]
    assert observed.metadata["expert_profile"] == str(profile)
    assert observed.hashes_complete()
    assert observed.artifact_digest != model.artifact_digest
    monkeypatch.setattr(
        real_executor.psutil, "virtual_memory", lambda: SimpleNamespace(available=32 * 1024**3)
    )
    parameters = {"mmap_experts": True, "resident_experts": False, "ple_io": "direct"}
    assert real_executor._strata_memory_failure(parameters, observed) is None
    profile.write_bytes(b"changed profile")
    failure = real_executor._strata_memory_failure(parameters, observed)
    assert failure and failure.kind.value == "UNSUPPORTED_MODEL"
