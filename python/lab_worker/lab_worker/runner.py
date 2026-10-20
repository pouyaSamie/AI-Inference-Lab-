"""Single native process runner with ownership, readiness and telemetry.

Every process is launched with an argv array (never a shell), in its own
process group, with a sanitized environment, an explicit sandbox and a
verified executable digest. Cancellation and timeout paths terminate only the
owned process group.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import IO

import httpx
from lab_core.base import utcnow

from lab_core import (
    CommandSpec,
    RawEvidenceRef,
    ReadinessKind,
    RegisteredBinary,
    SandboxPaths,
)

from .config import WorkerSettings
from .gpu import GpuLease
from .hardware import TelemetrySummary, process_start_ticks, sample_gpu
from .journal import WorkerJournal


class RunnerError(RuntimeError):
    pass


class ExecutableTrustError(RunnerError):
    pass


@dataclass
class RunResult:
    command_id: str
    stage: str
    executable: str
    argv: tuple[str, ...]
    pid: int | None
    exit_code: int | None
    duration_ms: int
    timed_out: bool
    cancelled: bool
    readiness_met: bool
    signal: int | None
    stdout_path: str
    stderr_path: str
    telemetry: TelemetrySummary
    process_start_ticks: int | None
    error: str | None = None
    artifacts: tuple[RawEvidenceRef, ...] = ()

    @property
    def succeeded(self) -> bool:
        return (
            self.exit_code == 0
            and not self.timed_out
            and not self.cancelled
            and self.readiness_met
            and self.error is None
        )

    def stdout_text(self, limit: int = 8 * 1024 * 1024) -> str:
        try:
            with Path(self.stdout_path).open("rb") as handle:
                return handle.read(limit).decode("utf-8", "replace")
        except OSError:
            return ""

    def stderr_text(self, limit: int = 64 * 1024) -> str:
        try:
            with Path(self.stderr_path).open("rb") as handle:
                return handle.read(limit).decode("utf-8", "replace")
        except OSError:
            return ""


@dataclass
class ServerProcess:
    result: RunResult
    _runner: ProcessRunner
    _process: subprocess.Popen[bytes]
    _lease: GpuLease | None
    _started: float = 0.0
    _stopped: bool = False

    def stop(self, *, grace_seconds: int | None = None) -> RunResult:
        if self._stopped:
            return self.result
        self._stopped = True
        self._runner._terminate(self._process, grace_seconds=grace_seconds)
        try:
            exit_code = self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            exit_code = None
        self.result.exit_code = exit_code
        self.result.duration_ms = max(0, int((time.monotonic() - self._started) * 1000))
        self._runner._close_handles(self._process.pid)
        self._runner.journal.process_finished(
            command_id=self.result.command_id,
            pid=self._process.pid,
            exit_code=exit_code,
            reason="server-stop",
        )
        return self.result


class ProcessRunner:
    def __init__(
        self,
        settings: WorkerSettings,
        *,
        binaries: dict[str, RegisteredBinary],
        journal: WorkerJournal,
    ) -> None:
        self.settings = settings
        self.binaries = binaries
        self.journal = journal
        self._handles: dict[int, tuple[IO[bytes], IO[bytes]]] = {}

    # ---------------------------------------------------------------- inputs
    def resolve_binary(self, command: CommandSpec) -> RegisteredBinary:
        binary = self.binaries.get(command.executable_id)
        if binary is None:
            raise ExecutableTrustError(f"executable_id {command.executable_id!r} is not registered")
        try:
            actual = _sha256_file(Path(binary.path))
        except OSError as exc:
            raise ExecutableTrustError(f"cannot hash registered executable {binary.path}: {exc}") from exc
        if actual != binary.sha256:
            raise ExecutableTrustError(
                f"registered executable changed: {binary.path}",
            )
        if command.executable_sha256 != binary.sha256:
            raise ExecutableTrustError(
                f"command executable digest does not match registry for {command.executable_id!r}"
            )
        return binary

    def _environment(
        self, binary: RegisteredBinary, sandbox: SandboxPaths, lease: GpuLease | None
    ) -> dict[str, str]:
        path = os.environ.get("PATH", "/usr/bin:/bin")
        env: dict[str, str] = {
            "PATH": path,
            "HOME": sandbox.temp_home,
            "TMPDIR": sandbox.temp_home,
            "TMP": sandbox.temp_home,
            "TEMP": sandbox.temp_home,
            "XDG_CACHE_HOME": str(Path(sandbox.temp_home) / ".cache"),
            "XDG_CONFIG_HOME": str(Path(sandbox.temp_home) / ".config"),
            "XDG_DATA_HOME": str(Path(sandbox.temp_home) / ".local/share"),
            "LC_ALL": "C",
            "LANG": "C",
            "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
            "PYTHONUNBUFFERED": "1",
        }
        if lease is not None and lease.visibility:
            env["CUDA_VISIBLE_DEVICES"] = lease.visibility
        if binary.engine_id.value == "llamacpp" and Path(self.settings.llama_lib_dir).is_dir():
            env["LD_LIBRARY_PATH"] = self.settings.llama_lib_dir
        if binary.engine_id.value == "strata" and Path(self.settings.strata_source_root).is_dir():
            env["PYTHONPATH"] = self.settings.strata_source_root
        for key in ("PATH", "HOME", "TMPDIR", "LC_ALL", "LANG", "CUDA_DEVICE_ORDER"):
            env.setdefault(key, "")
        return env

    def _logs(self, sandbox: SandboxPaths, stage: str, command_id: str) -> tuple[Path, Path]:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{stage}-{command_id}")[:120]
        return (
            Path(sandbox.log_dir) / f"{safe}.stdout.log",
            Path(sandbox.log_dir) / f"{safe}.stderr.log",
        )

    def _verify_cwd(self, sandbox: SandboxPaths, cwd: str) -> Path:
        root = Path(sandbox.root).resolve()
        value = Path(cwd).resolve()
        try:
            value.relative_to(root)
        except ValueError as exc:
            raise RunnerError("command cwd escapes the sandbox") from exc
        if not value.is_dir():
            raise RunnerError(f"command cwd does not exist: {value}")
        return value

    # -------------------------------------------------------------- execution
    def run_to_completion(
        self,
        *,
        command_id: str,
        stage: str,
        command: CommandSpec,
        sandbox: SandboxPaths,
        lease: GpuLease | None = None,
        cancel_event: Event | None = None,
        on_tick: Callable[[], None] | None = None,
    ) -> RunResult:
        binary = self.resolve_binary(command)
        cwd = self._verify_cwd(sandbox, command.cwd)
        stdout_path, stderr_path = self._logs(sandbox, stage, command_id)
        if not command.argv:
            raise RunnerError("command argv is empty")
        process = self._spawn(binary, command, cwd, sandbox, lease, stdout_path, stderr_path, command_id)
        started = time.monotonic()
        self.journal.process_started(
            command_id=command_id,
            pid=process.pid,
            pgid=process.pid,
            start_ticks=process_start_ticks(process.pid),
            executable=binary.path,
            argv=(str(binary.path), *command.argv),
            gpu_uuids=lease.uuids if lease else (),
            log_path=str(stdout_path),
        )
        telemetry = TelemetrySummary()
        readiness_met = command.readiness.kind is ReadinessKind.NONE
        error: str | None = None
        timed_out = False
        cancelled = False
        exit_code: int | None = None
        last_sample = 0.0
        last_tick = time.monotonic()
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    self._terminate(process, grace_seconds=self.settings.command_grace_seconds)
                    break
                if time.monotonic() - started > command.timeout_seconds:
                    timed_out = True
                    self._terminate(process, grace_seconds=self.settings.command_grace_seconds)
                    break
                now = time.monotonic()
                if on_tick is not None and now - last_tick >= self.settings.lease_renew_seconds:
                    last_tick = now
                    on_tick()
                if now - last_sample >= self.settings.telemetry_interval_ms / 1000.0:
                    last_sample = now
                    telemetry.samples.append(
                        sample_gpu(lease.uuid_list[0] if lease and lease.uuid_list else None, process.pid)
                    )
                if not readiness_met:
                    ready, reason = self._check_readiness(command, process, stdout_path)
                    if ready:
                        readiness_met = True
                    elif reason:
                        error = reason
                        self._terminate(process, grace_seconds=self.settings.command_grace_seconds)
                        break
                if process.poll() is not None:
                    exit_code = process.returncode
                    break
                time.sleep(0.1)
            if exit_code is None:
                try:
                    exit_code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._terminate(process, grace_seconds=2)
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        exit_code = process.wait(timeout=5)
            if (
                not readiness_met
                and exit_code == 0
                and error is None
                and command.readiness.kind is not ReadinessKind.NONE
            ):
                error = "process exited before readiness"
            telemetry.samples.append(
                sample_gpu(lease.uuid_list[0] if lease and lease.uuid_list else None, process.pid)
            )
        finally:
            if process.poll() is None:
                self._terminate(process, grace_seconds=self.settings.command_grace_seconds)
            self._close_handles(process.pid)
            self.journal.process_finished(
                command_id=command_id,
                pid=process.pid,
                exit_code=exit_code,
                reason="cancelled" if cancelled else ("timeout" if timed_out else "exit"),
            )
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        artifacts = self._write_manifest(
            command_id=command_id,
            stage=stage,
            binary=binary,
            command=command,
            sandbox=sandbox,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            exit_code=exit_code,
            duration_ms=duration_ms,
            timed_out=timed_out,
            cancelled=cancelled,
            telemetry=telemetry,
        )
        result = RunResult(
            command_id=command_id,
            stage=stage,
            executable=binary.path,
            argv=(str(binary.path), *command.argv),
            pid=process.pid,
            exit_code=exit_code,
            duration_ms=duration_ms,
            timed_out=timed_out,
            cancelled=cancelled,
            readiness_met=readiness_met,
            signal=process.returncode if process.returncode and process.returncode < 0 else None,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            telemetry=telemetry,
            process_start_ticks=process_start_ticks(process.pid),
            error=error,
            artifacts=artifacts,
        )
        if not result.succeeded and error is None:
            if cancelled:
                error = "process cancelled"
            elif timed_out:
                error = f"process exceeded {command.timeout_seconds}s timeout"
            elif not readiness_met:
                error = "readiness predicate was not satisfied"
            else:
                error = f"process exited with code {exit_code}"
            result.error = error
        return result

    def start_server(
        self,
        *,
        command_id: str,
        stage: str,
        command: CommandSpec,
        sandbox: SandboxPaths,
        lease: GpuLease | None = None,
        port: int,
        cancel_event: Event | None = None,
        on_tick: Callable[[], None] | None = None,
    ) -> tuple[ServerProcess | None, RunResult]:
        binary = self.resolve_binary(command)
        cwd = self._verify_cwd(sandbox, command.cwd)
        stdout_path, stderr_path = self._logs(sandbox, stage, command_id)
        process = self._spawn(binary, command, cwd, sandbox, lease, stdout_path, stderr_path, command_id)
        started = time.monotonic()
        self.journal.process_started(
            command_id=command_id,
            pid=process.pid,
            pgid=process.pid,
            start_ticks=process_start_ticks(process.pid),
            executable=binary.path,
            argv=(str(binary.path), *command.argv),
            gpu_uuids=lease.uuids if lease else (),
            log_path=str(stdout_path),
        )
        telemetry = TelemetrySummary()
        readiness_met = False
        error: str | None = None
        last_tick = time.monotonic()
        while time.monotonic() - started < command.readiness.timeout_seconds:
            now = time.monotonic()
            if on_tick is not None and now - last_tick >= self.settings.lease_renew_seconds:
                last_tick = now
                on_tick()
            if cancel_event is not None and cancel_event.is_set():
                error = "server start cancelled"
                break
            if process.poll() is not None:
                error = f"server exited during startup with code {process.returncode}"
                break
            ready, reason = self._check_readiness(command, process, stdout_path, port=port)
            if ready:
                readiness_met = True
                break
            if reason:
                error = reason
                break
            time.sleep(max(0.05, command.readiness.interval_ms / 1000.0))
        if readiness_met:
            telemetry.samples.append(
                sample_gpu(lease.uuid_list[0] if lease and lease.uuid_list else None, process.pid)
            )
            result = RunResult(
                command_id=command_id,
                stage=stage,
                executable=binary.path,
                argv=(str(binary.path), *command.argv),
                pid=process.pid,
                exit_code=None,
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                timed_out=False,
                cancelled=False,
                readiness_met=True,
                signal=None,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                telemetry=telemetry,
                process_start_ticks=process_start_ticks(process.pid),
            )
            server = ServerProcess(
                result=result, _runner=self, _process=process, _lease=lease, _started=started
            )
            return server, result
        self._terminate(process, grace_seconds=5)
        try:
            exit_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            exit_code = None
        self._close_handles(process.pid)
        self.journal.process_finished(
            command_id=command_id,
            pid=process.pid,
            exit_code=exit_code,
            reason="server-start-failed",
        )
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        result = RunResult(
            command_id=command_id,
            stage=stage,
            executable=binary.path,
            argv=(str(binary.path), *command.argv),
            pid=process.pid,
            exit_code=exit_code,
            duration_ms=duration_ms,
            timed_out=False,
            cancelled=bool(cancel_event and cancel_event.is_set()),
            readiness_met=False,
            signal=exit_code if exit_code and exit_code < 0 else None,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            telemetry=telemetry,
            process_start_ticks=None,
            error=error or "server did not become ready",
        )
        return None, result

    # --------------------------------------------------------------- internals
    def _spawn(
        self,
        binary: RegisteredBinary,
        command: CommandSpec,
        cwd: Path,
        sandbox: SandboxPaths,
        lease: GpuLease | None,
        stdout_path: Path,
        stderr_path: Path,
        command_id: str,
    ) -> subprocess.Popen[bytes]:
        env = self._environment(binary, sandbox, lease)
        for key, value in command.env.items():
            if key.upper() in {"LD_PRELOAD"}:
                raise RunnerError(f"refusing dangerous environment key {key}")
            if key.upper() in {"PATH", "HOME", "TMPDIR"}:
                continue
            env[key] = value
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_handle = stdout_path.open("wb")
        stderr_handle = stderr_path.open("wb")
        try:
            process = subprocess.Popen(
                (str(binary.path), *command.argv),
                cwd=str(cwd),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            stdout_handle.close()
            stderr_handle.close()
            raise RunnerError(
                f"could not start {binary.path} for {command_id}: {type(exc).__name__}: {exc}"
            ) from exc
        self._handles[process.pid] = (stdout_handle, stderr_handle)
        return process

    def _close_handles(self, pid: int) -> None:
        handles = self._handles.pop(pid, None)
        if handles is None:
            return
        for handle in handles:
            with contextlib.suppress(OSError):
                handle.close()

    def _check_readiness(
        self,
        command: CommandSpec,
        process: subprocess.Popen[bytes],
        stdout_path: Path,
        *,
        port: int | None = None,
    ) -> tuple[bool, str | None]:
        predicate = command.readiness
        if predicate.kind is ReadinessKind.NONE:
            return True, None
        if predicate.kind is ReadinessKind.PROCESS_ALIVE:
            if process.poll() is None:
                return True, None
            return False, f"process exited with code {process.returncode}"
        if predicate.kind is ReadinessKind.OUTPUT_PATTERN:
            if predicate.target is None:
                return False, "output readiness pattern is missing"
            try:
                text = stdout_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if re.search(predicate.target, text):
                return True, None
            if process.poll() is not None:
                return False, f"process exited with code {process.returncode} before pattern"
            return False, None
        if predicate.kind is ReadinessKind.HTTP:
            if predicate.target is None:
                return False, "HTTP readiness target is missing"
            target = predicate.target
            if "{port}" in target:
                if port is None:
                    return False, "HTTP readiness target needs a port"
                target = target.replace("{port}", str(port))
            try:
                response = httpx.get(target, timeout=1.0, trust_env=False)
            except httpx.HTTPError:
                if process.poll() is not None:
                    return False, f"process exited with code {process.returncode} before HTTP ready"
                return False, None
            if response.status_code == predicate.expected_status:
                return True, None
            if process.poll() is not None:
                return False, (
                    f"process exited with code {process.returncode}; readiness returned "
                    f"{response.status_code}"
                )
            return False, None
        return False, f"unsupported readiness kind {predicate.kind}"  # type: ignore[unreachable]

    def _terminate(self, process: subprocess.Popen[bytes], *, grace_seconds: int | None = None) -> None:
        if process.poll() is not None:
            return
        grace = self.settings.command_grace_seconds if grace_seconds is None else grace_seconds
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        deadline = time.monotonic() + max(1, grace)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return
            time.sleep(0.1)
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)

    def _write_manifest(
        self,
        *,
        command_id: str,
        stage: str,
        binary: RegisteredBinary,
        command: CommandSpec,
        sandbox: SandboxPaths,
        stdout_path: Path,
        stderr_path: Path,
        exit_code: int | None,
        duration_ms: int,
        timed_out: bool,
        cancelled: bool,
        telemetry: TelemetrySummary,
    ) -> tuple[RawEvidenceRef, ...]:
        refs: list[RawEvidenceRef] = []
        for path, content_type in ((stdout_path, "text/plain"), (stderr_path, "text/plain")):
            try:
                size = path.stat().st_size
                digest = _sha256_file(path)
            except OSError:
                continue
            refs.append(
                RawEvidenceRef(
                    path=str(path),
                    sha256=digest,
                    content_type=content_type,
                    size_bytes=size,
                    description=f"{stage} {path.name}",
                )
            )
        manifest = {
            "command_id": command_id,
            "stage": stage,
            "executable": binary.path,
            "executable_sha256": binary.sha256,
            "argv": list(command.argv),
            "cwd": command.cwd,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "cancelled": cancelled,
            "telemetry_samples": len(telemetry.samples),
            "telemetry_errors": telemetry.errors,
            "created_at": utcnow().isoformat(),
        }
        path = Path(sandbox.artifact_dir) / f"{stage}-{command_id}.manifest.json"
        try:
            path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            digest = _sha256_file(path)
            refs.append(
                RawEvidenceRef(
                    path=str(path),
                    sha256=digest,
                    content_type="application/json",
                    size_bytes=path.stat().st_size,
                    description=f"{stage} run manifest",
                )
            )
        except OSError:
            pass
        return tuple(refs)


def allocate_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
