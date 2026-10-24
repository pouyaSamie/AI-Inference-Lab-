"""Private packaged-desktop supervisor; never used by the public API entry point.

Secrets arrive on stdin, status on an inherited pipe. Each service remains an
independent process. EOF from the desktop always triggers ordered shutdown.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import logging.handlers
import os
import selectors
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any, TextIO

import httpx
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from .backup import _copy_database
from .config import Settings

MAX_MESSAGE = 65_536


def read_message(stream: TextIO) -> dict[str, Any]:
    line = stream.readline(MAX_MESSAGE + 1)
    if len(line) > MAX_MESSAGE or not line.endswith("\n"):
        raise ValueError("Invalid runtime message")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("Runtime message must be an object")
    return value


def migrate(root: Path, migrations: Path) -> None:
    """Reject unknown/newer schemas and snapshot both stores before upgrading."""
    config = Config()
    config.set_main_option("script_location", str(migrations))
    database = root / "controller.sqlite3"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}".replace("%", "%%"))
    scripts = ScriptDirectory.from_config(config)
    heads = set(scripts.get_heads())
    revisions: set[str] = set()
    if database.exists():
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            exists = connection.execute(
                "SELECT name FROM sqlite_master WHERE name='alembic_version'"
            ).fetchone()
            if exists:
                revisions = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
            elif connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                raise ValueError("Existing database has no supported migration history")
        known = {revision.revision for revision in scripts.walk_revisions()}
        if not revisions.issubset(known):
            raise ValueError("Database schema is newer than or incompatible with this application")
        if revisions != heads:
            backup = root / "backups" / f"before-migration-{time.time_ns()}"
            for label in ("controller", "optuna"):
                source = root / f"{label}.sqlite3"
                if source.exists():
                    _copy_database(source, backup / source.name)
    if revisions != heads:
        command.upgrade(config, "head")


def controller_settings(root: Path, secrets: dict[str, str], config: dict[str, Any]) -> Settings:
    return Settings(
        _env_file=None,
        environment="prod",
        controller_db_url=f"sqlite:///{root / 'controller.sqlite3'}",
        optimizer_db_url=f"sqlite:///{root / 'optuna.sqlite3'}",
        artifact_root=str(root / "artifacts"),
        allowed_model_roots=config.get("model_roots", []),
        operator_token=secrets["operator"],
        optimizer_token=secrets["optimizer"],
        enrollment_token=secrets["enrollment"],
        worker_token_pepper=secrets["pepper"],
        execution_mode="simulated" if config.get("simulation") else "real",
        allow_simulation=bool(config.get("simulation")),
        cors_origins=[],
        document_openapi=False,
    )


def renew_local_enrollment(root: Path, secrets: dict[str, str], config: dict[str, Any]) -> None:
    """Rotate only the owned local worker credential under the runtime lock.

    This preserves durable worker/job identity across a session-only pepper.
    Disabled workers remain disabled; other enrollment records are untouched.
    """
    from sqlalchemy.orm import Session

    from .db import create_controller_engine
    from .orm import WorkerRow
    from .security import hash_worker_token, new_worker_token, token_prefix

    settings = controller_settings(root, secrets, config)
    engine = create_controller_engine(settings)
    try:
        with Session(engine) as session:
            row = session.get(WorkerRow, config["worker_id"])
            if row is None:
                return
            if row.disabled:
                raise ValueError("The managed worker is disabled; review its enrollment before restarting")
            token = new_worker_token()
            row.token_sha256 = hash_worker_token(secrets["pepper"], token)
            row.token_prefix = token_prefix(token)
            row.roles = list(dict.fromkeys([*row.roles, "targeted-model-verification", "recipe-serving"]))
            row.status = "offline"
            row.serving_json = {}
            row.last_heartbeat_at = None
            state = root / "worker" / f"{config['worker_id']}.json"
            state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            value = json.loads(state.read_text()) if state.exists() else {}
            value.update(token=token, worker_id=config["worker_id"])
            temporary = state.with_suffix(".tmp")
            temporary.write_text(json.dumps(value) + "\n")
            temporary.chmod(0o600)
            # If interrupted between these operations, startup rotates again.
            session.commit()
            temporary.replace(state)
    finally:
        engine.dispose()


def worker_settings(root: Path, secrets: dict[str, str], config: dict[str, Any], url: str) -> Any:
    from lab_worker.config import WorkerSettings

    simulated = bool(config.get("simulation"))
    values = {
        key: config[key]
        for key in (
            "model_roots",
            "llama_server_path",
            "llama_bench_path",
            "llama_lib_dir",
            "strata_path",
            "strata_server_script",
            "strata_python",
        )
        if config.get(key)
    }
    # Never allow the source tree's workstation-specific defaults in packaged mode.
    for key in (
        "llama_server_path",
        "llama_bench_path",
        "llama_lib_dir",
        "strata_path",
        "strata_server_script",
        "strata_source_root",
        "strata_python",
    ):
        values.setdefault(key, str(root / "unconfigured"))
    values.setdefault("model_roots", [])
    return WorkerSettings(
        _env_file=None,
        controller_url=url,
        enrollment_token=secrets["enrollment"],
        worker_id=config["worker_id"],
        worker_name="Local desktop worker" if not simulated else "SIMULATED desktop test worker",
        state_file=str(root / "worker" / f"{config['worker_id']}.json"),
        state_root=str(root / "worker"),
        simulated=simulated,
        execution_mode="simulated" if simulated else "real",
        **values,
    )


def run_service(role: str, payload: dict[str, Any]) -> None:
    root = Path(payload["root"])
    config, secrets = payload["config"], payload["secrets"]
    stop = Event()
    if role == "controller":
        import uvicorn

        from .app import create_app

        listener = socket.socket(fileno=int(payload["socket_fd"]))
        app = create_app(controller_settings(root, secrets, config))
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                access_log=False,
                log_level="warning",
                timeout_graceful_shutdown=10,
            )
        )
        import asyncio

        async def serve() -> None:
            def stop_dispatch() -> None:
                runtime = getattr(app.state, "runtime", None)
                if runtime is not None:
                    runtime._stopping.set()

            asyncio.get_running_loop().add_signal_handler(signal.SIGUSR1, stop_dispatch)
            await server.serve(sockets=[listener])

        asyncio.run(serve())
        return
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if role == "optimizer":
        from lab_optimizer.config import OptimizerSettings
        from lab_optimizer.worker import OptimizerWorker

        optimizer = OptimizerWorker(
            OptimizerSettings(
                _env_file=None,
                controller_url=payload["url"],
                token=secrets["optimizer"],
                db_url=f"sqlite:///{root / 'optuna.sqlite3'}",
                optimizer_id=config["optimizer_id"],
            )
        )
        try:
            optimizer.run(stop)
        finally:
            optimizer.client.close()
    elif role == "worker":
        settings = worker_settings(root, secrets, config, payload["url"])
        if settings.simulated:
            from lab_worker.worker import SimulatedWorker

            worker: Any = SimulatedWorker(settings)
        else:
            from lab_worker.client import WorkerClient
            from lab_worker.discovery import discover_snapshot
            from lab_worker.real_executor import RealExecutor
            from lab_worker.real_worker import RealWorker

            client = WorkerClient(settings)
            previous = client._load_state()
            discovery = discover_snapshot(
                settings,
                revision=int(previous.get("snapshot_revision", 0)) + 1,
                hash_models=False,
            )
            worker = RealWorker(
                settings,
                client=client,
                executor=RealExecutor(
                    settings,
                    client=client,
                    discovery=discovery,
                ),
            )
        try:
            worker.run(stop)
        finally:
            worker.client.close()
    else:
        raise ValueError("Unknown service role")


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self.secrets = secrets

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self.secrets:
            if secret:
                message = message.replace(secret, "[REDACTED]")
        record.msg, record.args = message[:4000], ()
        return True


class Supervisor:
    def __init__(self, payload: dict[str, Any], status: TextIO) -> None:
        self.payload = payload
        self.payload["config"]["optimizer_id"] = f"desktop-opt-{os.getpid()}-{time.time_ns()}"
        self.root = Path(payload["root"])
        self.status = status
        self.children: dict[str, subprocess.Popen[str]] = {}
        self.attempts: dict[str, int] = {}
        self.started: dict[str, float] = {}
        self.stopping = False
        self.listener: socket.socket | None = None
        self.url = ""
        self.worker_usable = False
        self.inventory: dict[str, Any] = {}
        self.booted = time.time()
        self.import_command: str | None = None
        self.engine_candidates: list[Any] = []
        self.logger = logging.getLogger("desktop-runtime")

    def emit(self, state: str, message: str) -> None:
        for secret in self.payload["secrets"].values():
            message = message.replace(secret, "[REDACTED]")
        message = message[:400]
        self.logger.info("%s: %s", state, message)
        self.status.write(
            json.dumps(
                {
                    "state": state,
                    "message": message,
                    "url": self.url,
                    "inventory": self.inventory,
                    "engine_candidates": self.engine_candidates,
                }
            )
            + "\n"
        )
        self.status.flush()

    def spawn(self, role: str) -> None:
        inherited: tuple[int, ...] = ()
        self.started[role] = time.time()
        if role == "optimizer":
            self.payload["config"]["optimizer_id"] = f"desktop-opt-{time.time_ns()}"
        payload = {**self.payload, "url": self.url}
        if role == "controller":
            assert self.listener is not None
            inherited = (self.listener.fileno(),)
            payload["socket_fd"] = self.listener.fileno()
        child = subprocess.Popen(
            [sys.executable, "-I", sys.argv[0], role],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            pass_fds=inherited,
        )
        assert child.stdin is not None
        child.stdin.write(json.dumps(payload) + "\n")
        child.stdin.close()
        self.children[role] = child

    def wait_ready(self, role: str) -> None:
        deadline = time.monotonic() + (1800 if role == "worker" else 30)
        headers = {"Authorization": f"Bearer {self.payload['secrets']['operator']}"}
        with httpx.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline and not self.stopping:
                if self.children[role].poll() is not None:
                    raise RuntimeError(f"{role} exited during startup; inspect runtime logs")
                try:
                    response = client.get(self.url + "/api/v1/status", headers=headers)
                    if response.is_success:
                        value = response.json()
                        if role == "controller" or (
                            role == "optimizer"
                            and (
                                value["optimizer"]["online"]
                                and value["optimizer"]["optimizer_id"]
                                == self.payload["config"]["optimizer_id"]
                            )
                        ):
                            return
                        if role == "worker":
                            workers = client.get(self.url + "/api/v1/workers", headers=headers).json()
                            if any(
                                w["worker_id"] == self.payload["config"]["worker_id"]
                                and w["status"] == "online"
                                and w["snapshot_revision"] > 0
                                and datetime.fromisoformat(w["last_heartbeat_at"]).timestamp()
                                >= self.started[role]
                                for w in workers["workers"]
                            ):
                                worker_id = self.payload["config"]["worker_id"]
                                snapshot = client.get(
                                    self.url + f"/api/v1/workers/{worker_id}/snapshot", headers=headers
                                ).json()
                                self.update_inventory(snapshot)
                                return
                except httpx.HTTPError:
                    pass
                time.sleep(0.15)
        raise RuntimeError(f"{role} readiness timed out; inspect configuration and runtime logs")

    def stop_child(self, role: str) -> None:
        child = self.children.pop(role, None)
        if child is None:
            return
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=35)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        if child.stdout:
            child.stdout.close()
        if role == "worker" and not self.payload["config"].get("simulation"):
            from lab_worker.journal import WorkerJournal

            # Journal validates executable, process start ticks and group ownership.
            WorkerJournal(
                self.root / "worker/journal", self.payload["config"]["worker_id"]
            ).recover_owned_processes()

    def shutdown(self) -> None:
        self.stopping = True
        # Stop scheduler dispatch before cancelling the worker. Keep HTTP alive
        # until the worker posts its interrupted/cancelled outcome.
        controller = self.children.get("controller")
        if controller and controller.poll() is None:
            with contextlib.suppress(OSError):
                controller.send_signal(signal.SIGUSR1)
        failures: list[Exception] = []
        for role in ("worker", "optimizer", "controller"):
            try:
                self.stop_child(role)
            except Exception as exc:
                # A journal/recovery error must not orphan the other services.
                failures.append(exc)
        if self.listener:
            self.listener.close()
        if failures:
            raise ExceptionGroup("Local service shutdown failed", failures)

    def run(self, migrations: Path) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        with (self.root / "runtime.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Another runtime owns this application's data directory") from exc
            handler = logging.handlers.RotatingFileHandler(
                self.root / "runtime.log",
                maxBytes=1_048_576,
                backupCount=3,
            )
            handler.addFilter(RedactingFilter(list(self.payload["secrets"].values())))
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            try:
                self.emit("starting", "Checking local databases")
                migrate(self.root, migrations)
                renew_local_enrollment(self.root, self.payload["secrets"], self.payload["config"])
                self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.listener.bind(("127.0.0.1", 0))
                self.listener.listen(128)
                self.url = f"http://127.0.0.1:{self.listener.getsockname()[1]}"
                # SIGUSR1 is handled inside the controller to stop dispatch safely.
                for role in ("controller", "optimizer"):
                    self.emit("starting", f"Starting {role}")
                    self.spawn(role)
                    self.wait_ready(role)
                from lab_worker.engine_locations import discover_engine_locations

                self.engine_candidates = discover_engine_locations(
                    tuple(Path(item) for item in self.payload["config"].get("engine_roots", []))
                )
                config = self.payload["config"]
                # Browsing model inventory never depends on an engine or GPU.
                configured = bool(
                    config.get("model_roots") or config.get("llama_server_path") or config.get("strata_path")
                )
                if configured or config.get("simulation"):
                    self.emit("starting", "Reading model metadata and available hardware")
                    self.spawn("worker")
                    self.wait_ready("worker")
                if self.inventory.get("models", 0) > self.inventory.get(
                    "verified_models", 0
                ) and not config.get("simulation"):
                    headers = {"Authorization": f"Bearer {self.payload['secrets']['operator']}"}
                    status = httpx.get(
                        self.url + "/api/v1/status", headers=headers, trust_env=False, timeout=2
                    )
                    if status.is_success and status.json().get("experiments_active") == 0:
                        queued = httpx.post(
                            self.url + f"/api/v1/workers/{config['worker_id']}/verify-models",
                            headers=headers,
                            trust_env=False,
                            timeout=2,
                        )
                        if queued.is_success:
                            self.import_command = queued.json()["command_id"]
                            self.inventory["verification"] = {
                                "state": "queued",
                                "updated_at": time.time(),
                                "model_id": None,
                                "bytes_done": 0,
                                "bytes_total": 0,
                                "files_done": 0,
                                "files_total": 0,
                            }
                self.emit_inventory_status()
                self.monitor()
            finally:
                self.shutdown()
                self.logger.removeHandler(handler)
                handler.close()

    def update_inventory(self, snapshot: dict[str, Any]) -> None:
        verification = self.inventory.get("verification")
        current_progress = False
        progress = self.root / "worker/verification-progress.json"
        try:
            if progress.stat().st_size <= 16384:
                value = json.loads(progress.read_text())
                if value.get("updated_at", 0) >= self.booted:
                    verification = value
                    current_progress = True
        except (OSError, ValueError, TypeError):
            pass
        verified = sum(model["verified"] for model in snapshot["models"])
        if verification and verification.get("state") == "complete" and verified < len(snapshot["models"]):
            verification = {**verification, "state": "failed"} if current_progress else None
        self.worker_usable = bool(snapshot["engines"] and snapshot["models"] and snapshot["hardware"]["gpus"])
        self.inventory = {
            "models": len(snapshot["models"]),
            "engines": len(snapshot["engines"]),
            "gpus": len(snapshot["hardware"]["gpus"]),
            "verified_models": verified,
            "warnings": snapshot["health"].get("warnings", []),
            "verification": verification,
        }

    def emit_inventory_status(self) -> None:
        if self.worker_usable:
            total = self.inventory.get("models", 0)
            verified = self.inventory.get("verified_models", 0)
            self.emit(
                "ready",
                (
                    f"Local services running; {verified} of {total} models verified"
                    if verified < total
                    else "Models verified; ready for an execution preflight"
                ),
            )
            return
        models = self.inventory.get("models", 0)
        if not self.payload["config"].get("model_roots"):
            message = "Choose your model folder to discover models."
        elif not models:
            message = (
                "No supported models found in the selected folders. Check the folder paths and scan warnings."
            )
        elif not self.inventory.get("engines"):
            message = f"Found {models} models. Choose a discovered engine build to enable optimization."
        elif not self.inventory.get("gpus"):
            message = f"Found {models} models and an engine. No compatible GPU was detected."
        else:
            message = "Review discovery warnings before optimizing."
        self.emit("needs_configuration", message)

    def monitor(self) -> None:
        next_inventory_poll = time.monotonic() + 2
        with selectors.DefaultSelector() as selector:
            for role, child in self.children.items():
                assert child.stdout is not None
                os.set_blocking(child.stdout.fileno(), False)
                selector.register(child.stdout, selectors.EVENT_READ, role)
            while not self.stopping:
                for key, _ in selector.select(timeout=0.2):
                    stream = key.fileobj
                    assert hasattr(stream, "read")
                    data = stream.read(8192)
                    if data:
                        # Engine output can contain prompts; retain only supervisor
                        # lifecycle records, never untrusted service stdout.
                        continue
                if "worker" in self.children and time.monotonic() >= next_inventory_poll:
                    next_inventory_poll = time.monotonic() + 2
                    try:
                        worker_id = self.payload["config"]["worker_id"]
                        response = httpx.get(
                            self.url + f"/api/v1/workers/{worker_id}/snapshot",
                            headers={"Authorization": f"Bearer {self.payload['secrets']['operator']}"},
                            timeout=1,
                            trust_env=False,
                        )
                        if response.is_success:
                            previous = self.inventory
                            self.update_inventory(response.json())
                            if self.inventory != previous:
                                self.emit_inventory_status()
                    except httpx.HTTPError:
                        pass
                for role, child in list(self.children.items()):
                    if child.poll() is None:
                        continue
                    self.attempts[role] = self.attempts.get(role, 0) + 1
                    self.logger.warning(
                        "%s exited (%s), attempt %s", role, child.returncode, self.attempts[role]
                    )
                    if self.attempts[role] > 3:
                        raise RuntimeError(
                            f"{role} repeatedly exited; use Retry after checking configuration"
                        )
                    self.emit("starting", f"Recovering {role}")
                    if child.stdout:
                        selector.unregister(child.stdout)
                    self.stop_child(role)
                    time.sleep(min(2 ** self.attempts[role], 8))
                    self.spawn(role)
                    self.wait_ready(role)
                    replacement = self.children[role].stdout
                    assert replacement is not None
                    os.set_blocking(replacement.fileno(), False)
                    selector.register(replacement, selectors.EVENT_READ, role)
                    self.emit(
                        "ready" if self.worker_usable else "needs_configuration",
                        "Local runtime recovered",
                    )


def main() -> None:
    os.umask(0o077)
    payload = read_message(sys.stdin)
    if sys.argv[1] != "supervisor":
        run_service(sys.argv[1], payload)
        return
    status = os.fdopen(int(payload.get("status_fd", 3)), "w", buffering=1)
    supervisor = Supervisor(payload, status)

    def watch_parent() -> None:
        # A pipe read also detects a crashed Electron parent during migrations,
        # discovery or readiness, without depending on a GUI shutdown callback.
        sys.stdin.readline(MAX_MESSAGE)
        supervisor.stopping = True

    Thread(target=watch_parent, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: setattr(supervisor, "stopping", True))
    signal.signal(signal.SIGINT, lambda *_: setattr(supervisor, "stopping", True))
    try:
        supervisor.run(Path(payload["migrations"]))
    except Exception as exc:
        supervisor.emit("error", str(exc)[:400])
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
