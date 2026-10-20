"""Shared fixtures for offline controller, worker and optimizer tests."""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import httpx
import pytest
import uvicorn
from lab_api.app import create_app
from lab_api.config import Settings
from lab_api.db import create_controller_engine, create_session_factory
from lab_api.orm import Base
from lab_optimizer.config import OptimizerSettings
from lab_optimizer.worker import OptimizerWorker
from lab_worker.config import WorkerSettings
from lab_worker.worker import SimulatedWorker
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

OPERATOR_TOKEN = "test-operator-token-000000000000"
ENROLLMENT_TOKEN = "test-enrollment-token-0000000000"
OPTIMIZER_TOKEN = "test-optimizer-token-0000000000"
PEPPER = "test-worker-pepper-000000000000"


@dataclass
class ControllerHandle:
    settings: Settings
    base_url: str
    engine: Engine
    session_factory: sessionmaker[Session]
    server: uvicorn.Server
    thread: threading.Thread

    @property
    def operator_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {OPERATOR_TOKEN}"}

    def wait_healthy(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"{self.base_url}/health", timeout=0.5)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.02)
        raise AssertionError("controller did not become healthy")


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "controller_db_url": f"sqlite:///{tmp_path / 'controller.sqlite3'}",
        "optimizer_db_url": f"sqlite:///{tmp_path / 'optuna.sqlite3'}",
        "artifact_root": str(tmp_path / "artifacts"),
        "allowed_model_roots": [str(tmp_path / "models")],
        "operator_token": OPERATOR_TOKEN,
        "enrollment_token": ENROLLMENT_TOKEN,
        "optimizer_token": OPTIMIZER_TOKEN,
        "worker_token_pepper": PEPPER,
        "scheduler_enabled": True,
        "scheduler_interval_seconds": 0.05,
        "sse_poll_interval_seconds": 0.05,
        "sse_keepalive_seconds": 5,
        "worker_lease_seconds": 5,
        "worker_offline_after_seconds": 120,
        "snapshot_max_age_seconds": 3600,
        "optimizer_lease_seconds": 5,
        "optimizer_offline_after_seconds": 30,
        "log_level": "WARNING",
        "execution_mode": "simulated",
        "allow_simulation": True,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def controller(settings: Settings):
    engine = create_controller_engine(settings)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    app = create_app(settings, session_factory=factory, engine=engine)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_level="warning",
            access_log=False,
            lifespan="on",
            timeout_keep_alive=2,
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    handle = ControllerHandle(
        settings=settings,
        base_url=f"http://127.0.0.1:{port}",
        engine=engine,
        session_factory=factory,
        server=server,
        thread=thread,
    )
    handle.wait_healthy()
    try:
        yield handle
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        engine.dispose()
        sock.close()


@dataclass
class WorkerHandle:
    worker: SimulatedWorker
    stop: Event
    thread: threading.Thread

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=10)
        self.worker.client.close()


@pytest.fixture
def simulated_worker(controller: ControllerHandle, tmp_path: Path):
    settings = WorkerSettings(
        controller_url=controller.base_url,
        enrollment_token=ENROLLMENT_TOKEN,
        worker_id="sim-test",
        worker_name="offline simulated worker",
        state_file=str(tmp_path / "worker-state.json"),
        poll_seconds=0.1,
        heartbeat_seconds=1.0,
        max_commands=2,
    )
    worker = SimulatedWorker(settings)
    worker.ensure_enrolled()
    worker.sync_snapshot()
    worker.heartbeat()
    stop = Event()
    thread = threading.Thread(target=worker.run, args=(stop,), daemon=True)
    thread.start()
    handle = WorkerHandle(worker=worker, stop=stop, thread=thread)
    try:
        yield handle
    finally:
        handle.close()


@dataclass
class OptimizerHandle:
    worker: OptimizerWorker
    stop: Event
    thread: threading.Thread

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=10)
        self.worker.client.close()


@pytest.fixture
def optimizer(controller: ControllerHandle, tmp_path: Path):
    settings = OptimizerSettings(
        controller_url=controller.base_url,
        token=OPTIMIZER_TOKEN,
        db_url=f"sqlite:///{tmp_path / 'optuna-worker.sqlite3'}",
        optimizer_id="opt-test",
        poll_seconds=0.1,
        heartbeat_seconds=1.0,
        poll_max_requests=5,
    )
    worker = OptimizerWorker(settings)
    stop = Event()
    thread = threading.Thread(target=worker.run, args=(stop,), daemon=True)
    thread.start()
    handle = OptimizerHandle(worker=worker, stop=stop, thread=thread)
    try:
        yield handle
    finally:
        handle.close()


def plan_body(*, contexts: tuple[int, ...] = (4096,), max_candidates: int = 3) -> dict[str, object]:
    return {
        "worker_id": "sim-test",
        "engine_id": "llamacpp",
        "model_id": "qwen2.5-7b-instruct-q4_k_m",
        "objective": "balanced",
        "contexts": list(contexts),
        "search_depth": "quick",
        "search_policy": {
            "depth": "quick",
            "max_candidates": max_candidates,
            "screening_replications": 1,
            "finalist_count": 1,
            "final_replications": 1,
            "seed": 7,
        },
        "gpu_uuids": ["sim-GPU-0"],
    }
