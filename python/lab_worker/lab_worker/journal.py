"""Append-only worker journals and crash recovery.

The journal is local, mode 0600 and contains command identity, lease generation
and process ownership evidence. Lease tokens are required to reconcile an
in-flight command after a worker restart; they are never written to logs.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lab_core.base import utcnow

from .hardware import process_is_alive, process_start_ticks


@dataclass(frozen=True)
class InterruptedCommand:
    command_id: str
    lease_token: str
    lease_generation: int
    experiment_id: str | None
    pid: int | None
    output_tail: str


class WorkerJournal:
    def __init__(self, root: Path, worker_id: str) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = root / f"{worker_id}.jsonl"
        self._lock = threading.Lock()
        if not self.path.exists():
            self.path.touch(mode=0o600)
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)

    def append(self, record: dict[str, Any]) -> None:
        payload = {"at": utcnow().isoformat(), **record}
        line = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)

    def records(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        values: list[dict[str, Any]] = []
        for line in lines:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                values.append(value)
        return values

    # -------------------------------------------------------------- lifecycle
    def command_started(
        self,
        *,
        command_id: str,
        command_type: str,
        lease_token: str,
        lease_generation: int,
        experiment_id: str | None,
    ) -> None:
        self.append(
            {
                "kind": "command.started",
                "command_id": command_id,
                "command_type": command_type,
                "lease_token": lease_token,
                "lease_generation": lease_generation,
                "experiment_id": experiment_id,
            }
        )

    def process_started(
        self,
        *,
        command_id: str,
        pid: int,
        pgid: int,
        start_ticks: int | None,
        executable: str,
        argv: tuple[str, ...],
        gpu_uuids: tuple[str, ...],
        log_path: str,
    ) -> None:
        self.append(
            {
                "kind": "process.started",
                "command_id": command_id,
                "pid": pid,
                "pgid": pgid,
                "start_ticks": start_ticks,
                "executable": executable,
                "argv": list(argv),
                "gpu_uuids": list(gpu_uuids),
                "log_path": log_path,
            }
        )

    def process_finished(self, *, command_id: str, pid: int, exit_code: int | None, reason: str) -> None:
        self.append(
            {
                "kind": "process.finished",
                "command_id": command_id,
                "pid": pid,
                "exit_code": exit_code,
                "reason": reason,
            }
        )

    def command_finished(self, *, command_id: str, outcome: str) -> None:
        self.append({"kind": "command.finished", "command_id": command_id, "outcome": outcome})

    def interrupted(self) -> tuple[InterruptedCommand, ...]:
        """Find commands that started but never reached a terminal journal event."""
        records = self.records()
        commands: dict[str, dict[str, Any]] = {}
        processes: dict[str, dict[str, Any]] = {}
        finished: set[str] = set()
        for record in records:
            kind = record.get("kind")
            command_id = record.get("command_id")
            if not isinstance(command_id, str):
                continue
            if kind == "command.started":
                commands[command_id] = record
            elif kind == "process.started":
                processes[command_id] = record
            elif kind == "command.finished":
                finished.add(command_id)
        result: list[InterruptedCommand] = []
        for command_id, record in commands.items():
            if command_id in finished:
                continue
            token = record.get("lease_token")
            generation = record.get("lease_generation")
            if not isinstance(token, str) or not isinstance(generation, int):
                continue
            process = processes.get(command_id, {})
            pid = process.get("pid") if isinstance(process.get("pid"), int) else None
            output_tail = ""
            log_path = process.get("log_path")
            if isinstance(log_path, str):
                with contextlib.suppress(OSError):
                    text = Path(log_path).read_text(encoding="utf-8", errors="replace")
                    output_tail = text[-4000:]
            result.append(
                InterruptedCommand(
                    command_id=command_id,
                    lease_token=token,
                    lease_generation=generation,
                    experiment_id=record.get("experiment_id")
                    if isinstance(record.get("experiment_id"), str)
                    else None,
                    pid=pid,
                    output_tail=output_tail,
                )
            )
        return tuple(result)

    def recover_owned_processes(self) -> tuple[int, ...]:
        """Terminate only process groups recorded as owned by this worker."""
        records = self.records()
        active: dict[int, dict[str, Any]] = {}
        finished: set[int] = set()
        for record in records:
            if record.get("kind") == "process.started" and isinstance(record.get("pid"), int):
                active[int(record["pid"])] = record
            elif record.get("kind") == "process.finished" and isinstance(record.get("pid"), int):
                finished.add(int(record["pid"]))
        killed: list[int] = []
        for pid, record in active.items():
            if pid in finished:
                continue
            start_ticks = record.get("start_ticks")
            if not isinstance(start_ticks, int):
                start_ticks = None
            if not process_is_alive(pid, start_ticks):
                continue
            pgid = record.get("pgid")
            if not isinstance(pgid, int):
                continue
            current = process_start_ticks(pid)
            if start_ticks is not None and current is not None and abs(current - start_ticks) > 2_000_000:
                continue
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                continue
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if not process_is_alive(pid, start_ticks):
                    break
                time.sleep(0.1)
            if process_is_alive(pid, start_ticks):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pgid, signal.SIGKILL)
            killed.append(pid)
            self.append(
                {
                    "kind": "process.recovered",
                    "pid": pid,
                    "command_id": record.get("command_id"),
                    "reason": "worker restart: owned process group terminated",
                }
            )
        return tuple(killed)

    def prune_completed(self, *, keep_last: int = 5000) -> None:
        """Bound journal growth without rewriting an active process record."""
        if keep_last <= 0:
            return
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            if len(lines) <= keep_last:
                return
            temp = self.path.with_suffix(".tmp")
            with temp.open("w", encoding="utf-8") as handle:
                handle.write("\n".join(lines[-keep_last:]) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
            with contextlib.suppress(OSError):
                self.path.chmod(0o600)
