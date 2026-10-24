"""Managed desktop migration, isolation and real subprocess lifecycle tests."""

from __future__ import annotations

import io
import json
import logging
import os
import selectors
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from lab_api.desktop_runtime import (
    RedactingFilter,
    controller_settings,
    migrate,
    read_message,
    worker_settings,
)

from tests.conftest import plan_body

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "python/lab_api/migrations"
SECRETS = {
    key: f"desktop-test-{key}-" + "a" * 32 for key in ("operator", "optimizer", "enrollment", "pepper")
}


def test_migration_refuses_future_schema_without_mutating_it(tmp_path: Path) -> None:
    database = tmp_path / "controller.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.execute("INSERT INTO alembic_version VALUES ('future-unknown-revision')")
    before = database.read_bytes()
    with pytest.raises(ValueError, match="newer than"):
        migrate(tmp_path, MIGRATIONS)
    assert database.read_bytes() == before


def test_upgrade_snapshots_existing_managed_stores(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'controller.sqlite3'}")
    command.upgrade(config, "b151f9870480")
    with sqlite3.connect(tmp_path / "optuna.sqlite3") as connection:
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.execute("INSERT INTO marker VALUES ('preserve me')")
    migrate(tmp_path, MIGRATIONS)
    backups = list((tmp_path / "backups").glob("*"))
    assert len(backups) == 1
    assert {p.name for p in backups[0].iterdir()} == {"controller.sqlite3", "optuna.sqlite3"}
    with sqlite3.connect(backups[0] / "optuna.sqlite3") as connection:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("preserve me",)
    migrate(tmp_path, MIGRATIONS)
    assert len(list((tmp_path / "backups").iterdir())) == 1


def test_session_reenrollment_never_enables_a_disabled_worker(tmp_path: Path) -> None:
    from lab_api.db import create_controller_engine
    from lab_api.desktop_runtime import renew_local_enrollment
    from lab_api.orm import WorkerRow
    from sqlalchemy.orm import Session

    from lab_core import utcnow

    migrate(tmp_path, MIGRATIONS)
    engine = create_controller_engine(controller_settings(tmp_path, SECRETS, {}))
    try:
        with Session(engine) as session:
            session.add(
                WorkerRow(
                    worker_id="desktop-local",
                    name="Local",
                    version="1.0.0",
                    protocol_version="1",
                    platform="linux",
                    roles=["real"],
                    enrolled_at=utcnow(),
                    disabled=True,
                    token_prefix="old-prefix",
                    token_sha256="a" * 64,
                )
            )
            session.commit()
        with pytest.raises(ValueError, match="disabled"):
            renew_local_enrollment(tmp_path, SECRETS, {"worker_id": "desktop-local"})
        with Session(engine) as session:
            worker = session.get(WorkerRow, "desktop-local")
            assert worker is not None and worker.disabled
            assert worker.token_sha256 == "a" * 64
    finally:
        engine.dispose()


def test_private_messages_and_redaction() -> None:
    for value in ("[]\n", "{}", "x" * 70_000 + "\n"):
        with pytest.raises(ValueError):
            read_message(io.StringIO(value))
    record = logging.LogRecord("test", logging.ERROR, "", 0, "token=%s", (SECRETS["operator"],), None)
    assert RedactingFilter(list(SECRETS.values())).filter(record)
    assert SECRETS["operator"] not in record.getMessage()


def test_packaged_configuration_ignores_dotenv_and_machine_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text('LAB_API_PORT=12345\nLAB_WORKER_MODEL_ROOTS=["/private/model"]\n')
    settings = controller_settings(tmp_path, SECRETS, {})
    assert settings.api_port == 8787
    assert settings.allowed_model_roots == []
    assert settings.allow_simulation is False
    worker = worker_settings(tmp_path, SECRETS, {"worker_id": "test-local"}, "http://127.0.0.1:1")
    assert worker.model_roots == []
    assert "/home/pouya" not in worker.llama_server_path
    assert worker.strata_python != sys.executable


class RuntimeProcess:
    def __init__(
        self, root: Path, bootstrap: Path, *, simulation: bool = True, config: dict[str, Any] | None = None
    ) -> None:
        self.root = root
        read_fd, write_fd = os.pipe()
        backend = os.environ.get("LAB_TEST_BUNDLED_BACKEND")
        python = str(Path(backend) / "python/bin/python3") if backend else sys.executable
        entry = str(Path(backend) / "bootstrap.py") if backend else str(bootstrap)
        migrations = str(Path(backend) / "migrations") if backend else str(MIGRATIONS)
        self.process = subprocess.Popen(
            [python, "-I", entry, "supervisor"],
            cwd=root.parent,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            pass_fds=(write_fd,),
        )
        self.reader = os.fdopen(read_fd, "rb", buffering=0)
        os.close(write_fd)
        assert self.process.stdin is not None
        self.process.stdin.write(
            json.dumps(
                {
                    "root": str(root),
                    "migrations": migrations,
                    "status_fd": write_fd,
                    "config": {"simulation": simulation, "worker_id": "sim-test", **(config or {})},
                    "secrets": SECRETS,
                }
            )
            + "\n"
        )
        self.process.stdin.flush()

    def status(self, timeout: float = 40) -> dict[str, Any]:
        with selectors.DefaultSelector() as selector:
            selector.register(self.reader, selectors.EVENT_READ)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if selector.select(timeout=0.2):
                    line = self.reader.readline()
                    if not line:
                        assert self.process.stderr is not None
                        pytest.fail(f"runtime exited: {self.process.stderr.read()}")
                    message = json.loads(line)
                    if message["state"] in {"ready", "error", "needs_configuration"}:
                        return message
            pytest.fail("runtime startup timed out")

    def close(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()
        try:
            self.process.wait(timeout=50)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
            self.reader.close()
            if self.process.stderr:
                self.process.stderr.close()


@pytest.fixture
def bootstrap(tmp_path: Path) -> Path:
    path = tmp_path / "bootstrap.py"
    # Source tests use the existing venv's installed editable packages. Packaged
    # smoke runs instead use only the staged interpreter and package tree.
    path.write_text("from lab_api.desktop_runtime import main\nmain()\n")
    return path


@pytest.mark.integration
def test_managed_runtime_end_to_end_and_recovery(tmp_path: Path, bootstrap: Path) -> None:
    root = tmp_path / "managed"
    runtime = RuntimeProcess(root, bootstrap)
    try:
        status = runtime.status()
        assert status["state"] == "ready", status
        headers = {"Authorization": f"Bearer {SECRETS['operator']}"}
        with httpx.Client(base_url=status["url"], headers=headers, timeout=5, trust_env=False) as client:
            assert client.get("/api/v1/status").json()["optimizer"]["online"]
            duplicate = RuntimeProcess(root, bootstrap)
            try:
                assert duplicate.status()["state"] == "error"
            finally:
                duplicate.close()
            plan = client.post("/api/v1/experiments/plan", json=plan_body(max_candidates=3))
            assert plan.status_code == 200, plan.text
            created = client.post(
                "/api/v1/experiments",
                json={"plan": plan.json()["plan"]},
                headers={"Idempotency-Key": "desktop-runtime-e2e"},
            )
            assert created.status_code == 201, created.text
            experiment = created.json()["status"]["experiment_id"]
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                result = client.get(f"/api/v1/experiments/{experiment}").json()
                if result["status"]["state"] == "completed":
                    break
                time.sleep(0.2)
            assert result["status"]["state"] == "completed", result
            assert all(row["simulated"] for row in result["observations"])
            candidate = result["candidates"][0]["candidate_id"]
            assert (
                client.post(
                    "/api/v1/recipes",
                    json={"experiment_id": experiment, "candidate_id": candidate},
                    headers={"Idempotency-Key": "desktop-no-simulated-recipe"},
                ).status_code
                == 409
            )
            # Kill just the supervised controller; the same owned listening
            # socket and credentials must reconnect the optimizer and worker.
            import psutil

            children = psutil.Process(runtime.process.pid).children()
            controller = next(p for p in children if p.cmdline()[-1] == "controller")
            controller.send_signal(signal.SIGKILL)
            recovered = runtime.status()
            assert recovered["state"] == "ready", recovered
            assert client.get(f"/api/v1/experiments/{experiment}").status_code == 200
    finally:
        runtime.close()
    assert runtime.process.returncode == 0
    SECRETS["pepper"] = "rotated-session-pepper-" + "b" * 32
    restarted = RuntimeProcess(root, bootstrap)
    try:
        again = restarted.status()
        assert again["state"] == "ready", again
        with httpx.Client(base_url=again["url"], headers=headers, trust_env=False) as client:
            assert client.get(f"/api/v1/experiments/{experiment}").status_code == 200
    finally:
        restarted.close()
    assert (root / "controller.sqlite3").exists()
    assert (root / "optuna.sqlite3").exists()
    assert root.stat().st_mode & 0o777 == 0o700
    assert SECRETS["operator"] not in (root / "runtime.log").read_text()


@pytest.mark.integration
def test_missing_configuration_and_parent_eof_shutdown(tmp_path: Path, bootstrap: Path) -> None:
    runtime = RuntimeProcess(tmp_path / "unconfigured", bootstrap, simulation=False)
    try:
        assert runtime.status()["state"] == "needs_configuration"
        import psutil

        children = psutil.Process(runtime.process.pid).children()
        assert len(children) == 2
    finally:
        runtime.close()
    assert all(not child.is_running() for child in children)


@pytest.mark.integration
def test_model_folder_inventory_does_not_require_engine_or_gpu(tmp_path: Path, bootstrap: Path) -> None:
    from tests.test_real_worker_units import write_gguf

    models = tmp_path / "models"
    gguf = models / "Strata-Named-Folder/models/Q2_0/Example-00001-of-00002.gguf"
    write_gguf(gguf, {"general.architecture": "qwen2", "general.name": "Example"})
    write_gguf(gguf.with_name("Example-00002-of-00002.gguf"), {"general.architecture": "qwen2"})
    before = gguf.read_bytes()
    runtime = RuntimeProcess(
        tmp_path / "model-only", bootstrap, simulation=False, config={"model_roots": [str(models)]}
    )
    try:
        status = runtime.status()
        assert status["state"] == "needs_configuration", status
        assert status["inventory"]["models"] == 1
        assert status["inventory"]["engines"] == 0
        assert "Found 1 models" in status["message"]
        headers = {"Authorization": f"Bearer {SECRETS['operator']}"}
        with httpx.Client(base_url=status["url"], headers=headers, trust_env=False) as client:
            snapshot = client.get("/api/v1/workers/sim-test/snapshot").json()
            assert len(snapshot["models"]) == 1
            assert len(snapshot["models"][0]["files"]) == 2
            assert snapshot["engines"] == []
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                snapshot = client.get("/api/v1/workers/sim-test/snapshot").json()
                if snapshot["models"][0]["verified"]:
                    break
                time.sleep(0.05)
            assert snapshot["models"][0]["verified"] is True
            commands = client.get("/api/v1/workers/sim-test/commands").json()
            assert len([item for item in commands if item["command_type"] == "SCAN"]) == 1
    finally:
        runtime.close()
    assert gguf.read_bytes() == before


def test_shutdown_stops_remaining_services_after_recovery_error(tmp_path, monkeypatch):
    import socket

    from lab_api.desktop_runtime import Supervisor

    runtime = Supervisor({"root": str(tmp_path), "config": {}, "secrets": SECRETS}, io.StringIO())
    runtime.listener = socket.socket()
    stopped = []

    def stop(role):
        stopped.append(role)
        if role == "worker":
            raise RuntimeError("journal recovery unavailable")

    monkeypatch.setattr(runtime, "stop_child", stop)
    with pytest.raises(ExceptionGroup, match="Local service shutdown failed"):
        runtime.shutdown()
    assert stopped == ["worker", "optimizer", "controller"]
    assert runtime.listener.fileno() == -1


def test_inventory_discards_stale_verification_and_explains_pending_models(tmp_path):
    from lab_api.desktop_runtime import Supervisor

    stream = io.StringIO()
    runtime = Supervisor({"root": str(tmp_path), "config": {}, "secrets": SECRETS}, stream)
    snapshot = {
        "engines": [object()],
        "models": [{"verified": False}],
        "hardware": {"gpus": [object()]},
        "health": {"warnings": []},
    }
    runtime.inventory["verification"] = {"state": "complete"}
    runtime.update_inventory(snapshot)
    assert runtime.inventory["verification"] is None
    runtime.emit_inventory_status()
    assert "0 of 1 models verified" in json.loads(stream.getvalue().splitlines()[-1])["message"]
    snapshot["models"][0]["verified"] = True
    runtime.update_inventory(snapshot)
    runtime.emit_inventory_status()
    assert "ready for an execution preflight" in json.loads(stream.getvalue().splitlines()[-1])["message"]


def test_current_completed_scan_retains_incomplete_verification_warning(tmp_path):
    from lab_api.desktop_runtime import Supervisor

    runtime = Supervisor({"root": str(tmp_path), "config": {}, "secrets": SECRETS}, io.StringIO())
    progress = tmp_path / "worker/verification-progress.json"
    progress.parent.mkdir()
    progress.write_text(json.dumps({"state": "complete", "updated_at": time.time(), "bytes_done": 100}))
    runtime.update_inventory(
        {
            "engines": [],
            "models": [{"verified": False}],
            "hardware": {"gpus": []},
            "health": {"warnings": []},
        }
    )
    assert runtime.inventory["verification"]["state"] == "failed"
    assert runtime.inventory["verification"]["bytes_done"] == 100
