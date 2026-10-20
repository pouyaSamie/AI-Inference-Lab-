"""Exclusive, UUID-addressed GPU leases.

A lease is an advisory ``flock`` on a per-UUID lock file plus a JSON owner
record. The kernel releases the lock if the worker dies, so recovery never
needs to kill an unrelated process. Callers that hold several GPUs acquire in
sorted order to avoid lock-order deadlocks.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from lab_core.base import utcnow
from lab_core.ids import sha256_text

_SAFE_UUID = re.compile(r"^(GPU|MIG)-[A-Za-z0-9-]+$")


class GpuLeaseError(RuntimeError):
    pass


@dataclass
class HeldGpu:
    uuid: str
    lock_path: Path
    owner_path: Path
    handle: IO[str]
    lease_id: str


class GpuLease:
    def __init__(self, manager: GpuLeaseManager, held: list[HeldGpu], command_id: str) -> None:
        self._manager = manager
        self._held = held
        self.command_id = command_id
        self.lease_id = held[0].lease_id if held else sha256_text(command_id)[:16]
        self.uuid_list = tuple(item.uuid for item in held)

    @property
    def uuids(self) -> tuple[str, ...]:
        return self.uuid_list

    @property
    def visibility(self) -> str:
        return ",".join(self.uuid_list)

    def release(self) -> None:
        self._manager.release(self)

    def __enter__(self) -> GpuLease:
        return self

    def __exit__(self, *args: object) -> None:
        self.release()


class GpuLeaseManager:
    def __init__(self, root: Path, worker_id: str) -> None:
        self.root = root
        self.worker_id = worker_id
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._active: dict[str, HeldGpu] = {}
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []

    def _path(self, uuid: str) -> tuple[Path, Path]:
        if not _SAFE_UUID.fullmatch(uuid):
            raise GpuLeaseError(f"refusing unsafe GPU UUID: {uuid!r}")
        stem = uuid.replace("/", "_")
        return self.root / f"{stem}.lock", self.root / f"{stem}.json"

    def acquire(self, uuids: tuple[str, ...], *, command_id: str) -> GpuLease:
        unique = tuple(sorted(set(uuids)))
        if not unique:
            return GpuLease(self, [], command_id)
        held: list[HeldGpu] = []
        lease_id = sha256_text(f"{self.worker_id}|{command_id}|{','.join(unique)}|{utcnow().isoformat()}")[
            :24
        ]
        try:
            for uuid in unique:
                lock_path, owner_path = self._path(uuid)
                handle = lock_path.open("a+", encoding="utf-8")
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    handle.close()
                    raise GpuLeaseError(f"GPU {uuid} is already leased") from exc
                owner = {
                    "uuid": uuid,
                    "worker_id": self.worker_id,
                    "command_id": command_id,
                    "lease_id": lease_id,
                    "pid": os.getpid(),
                    "acquired_at": utcnow().isoformat(),
                }
                owner_path.write_text(json.dumps(owner, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                with contextlib.suppress(OSError):
                    owner_path.chmod(0o600)
                held.append(
                    HeldGpu(
                        uuid=uuid,
                        lock_path=lock_path,
                        owner_path=owner_path,
                        handle=handle,
                        lease_id=lease_id,
                    )
                )
                with self._lock:
                    self._active[uuid] = held[-1]
        except Exception:
            for item in reversed(held):
                with contextlib.suppress(OSError):
                    fcntl.flock(item.handle.fileno(), fcntl.LOCK_UN)
                with contextlib.suppress(OSError):
                    item.handle.close()
                with contextlib.suppress(OSError):
                    item.owner_path.unlink()
                with self._lock:
                    self._active.pop(item.uuid, None)
            raise
        lease = GpuLease(self, held, command_id)
        self._events.append(
            {
                "event": "acquired",
                "lease_id": lease_id,
                "uuids": list(unique),
                "command_id": command_id,
                "at": utcnow().isoformat(),
            }
        )
        return lease

    def release(self, lease: GpuLease) -> None:
        for item in reversed(lease._held):
            with contextlib.suppress(OSError):
                item.owner_path.unlink()
            with contextlib.suppress(OSError):
                fcntl.flock(item.handle.fileno(), fcntl.LOCK_UN)
            with contextlib.suppress(OSError):
                item.handle.close()
            with self._lock:
                self._active.pop(item.uuid, None)
        lease._held.clear()
        self._events.append(
            {
                "event": "released",
                "lease_id": lease.lease_id,
                "uuids": list(lease.uuid_list),
                "command_id": lease.command_id,
                "at": utcnow().isoformat(),
            }
        )

    def active(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._active))

    def stale_records(self) -> tuple[Path, ...]:
        stale: list[Path] = []
        for path in self.root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("worker_id") != self.worker_id:
                continue
            uuid = payload.get("uuid")
            if not isinstance(uuid, str):
                continue
            lock_path, _ = self._path(uuid)
            if not lock_path.exists():
                continue
            try:
                with lock_path.open("a+", encoding="utf-8") as handle:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                continue
            stale.append(path)
        return tuple(stale)
