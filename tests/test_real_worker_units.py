"""Unit coverage for the real worker's local building blocks.

These tests never download weights, launch an inference engine, or require a
GPU. They use a tiny synthetic GGUF file and a trusted Python interpreter to
exercise the same process, lease and journal paths the real worker uses.
"""

from __future__ import annotations

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
