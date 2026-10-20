"""Real Linux worker loop: enrollment, inventory, heartbeats and commands."""

from __future__ import annotations

import contextlib
import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from typing import Any

from lab_core.base import utcnow
from lab_core.ids import stable_id

from lab_core import CommandType, WorkerCommandLease, WorkerHealth

from .client import WorkerClient, WorkerClientError
from .config import WorkerSettings
from .discovery import discover_snapshot
from .real_executor import RealExecutor
from .sandbox import cleanup_sandboxes

logger = logging.getLogger(__name__)


class RealWorker:
    def __init__(
        self,
        settings: WorkerSettings,
        *,
        client: WorkerClient | None = None,
        executor: RealExecutor | None = None,
        initial_discovery: bool = True,
    ) -> None:
        self.settings = settings
        settings.ensure_directories()
        self.client = client or WorkerClient(settings)
        self._last_heartbeat = 0.0
        self.processed = 0
        if executor is not None:
            self.executor = executor
        else:
            discovery = None
            if initial_discovery:
                discovery = discover_snapshot(
                    settings,
                    revision=self._next_revision(),
                    include_models=False,
                    include_engines=True,
                    include_hardware=True,
                    hash_models=False,
                )
            self.executor = RealExecutor(settings, client=self.client, discovery=discovery)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lab-worker-command")
        self._future: Future[None] | None = None
        self._stop = Event()

    # --------------------------------------------------------------- lifecycle
    def _state(self) -> dict[str, Any]:
        return self.client._load_state()

    def _next_revision(self) -> int:
        state = self._state()
        try:
            return max(1, int(state.get("snapshot_revision", 0)) + 1)
        except (TypeError, ValueError):
            return 1

    def _save_snapshot_state(self) -> None:
        snapshot = self.executor.current_snapshot()
        if snapshot is None:
            return
        self.client.save_state(
            snapshot_revision=snapshot.revision,
            worker_id=self.settings.worker_id,
        )

    def ensure_enrolled(self) -> None:
        if self.client.token:
            return
        if not self.settings.enrollment_token:
            raise WorkerClientError("no worker token is available and no enrollment token was configured")
        try:
            self.client.register()
        except WorkerClientError as exc:
            if "409" in str(exc):
                raise WorkerClientError(
                    "worker_id is already enrolled; pass its token with --worker-token "
                    "or remove the stale enrollment"
                ) from exc
            raise

    def recover(self) -> None:
        killed = self.executor.journal.recover_owned_processes()
        if killed:
            logger.warning("terminated owned orphan process groups after restart: %s", list(killed))
        interrupted = self.executor.journal.interrupted()
        if interrupted:
            logger.warning(
                "interrupted commands will be retried after their leases expire",
                extra={"commands": [item.command_id for item in interrupted]},
            )
        for stale in self.executor.leases.stale_records():
            with contextlib.suppress(OSError):
                stale.unlink()
        removed = cleanup_sandboxes(self.settings)
        if removed:
            logger.info("removed old sandboxes", extra={"count": removed})

    def sync_snapshot(self) -> None:
        for attempt in range(5):
            snapshot = self.executor.current_snapshot()
            if snapshot is None:
                discovery = discover_snapshot(
                    self.settings,
                    revision=self._next_revision(),
                    include_models=False,
                    hash_models=False,
                )
                self.executor.discovery = discovery
                self.executor._last_scan = discovery
                self.executor._snapshot_revision = discovery.snapshot.revision
                self.executor._engines = discovery.engines
                self.executor._reindex()
                snapshot = discovery.snapshot
            try:
                self.client.upload_snapshot(snapshot)
                self._save_snapshot_state()
                return
            except WorkerClientError as exc:
                if "409" not in str(exc):
                    raise
                revision = snapshot.revision + 1
                now = utcnow()
                snapshot = snapshot.model_copy(
                    update={
                        "revision": revision,
                        "snapshot_id": stable_id("snap", self.settings.worker_id, revision, now.isoformat()),
                        "created_at": now,
                    }
                )
                if self.executor.discovery is not None:
                    self.executor.discovery = replace(self.executor.discovery, snapshot=snapshot)
                self.executor._last_scan = self.executor.discovery
                self.executor._snapshot_revision = revision
                logger.warning("snapshot revision conflict; retrying with revision %s", revision)
                logger.debug("snapshot upload retry %s", attempt)
        raise WorkerClientError("could not upload a monotonic snapshot after 5 revisions")

    def heartbeat(self) -> None:
        snapshot = self.executor.current_snapshot()
        revision = snapshot.revision if snapshot is not None else 0
        warnings = ["REAL_EXECUTION"]
        if snapshot is not None:
            warnings.extend(snapshot.hardware.contamination_warnings)
        health = WorkerHealth(
            status="online",
            last_heartbeat_at=utcnow(),
            active_leases=self.executor.leases.active(),
            owned_pids=(),
            isolated=True,
            warnings=tuple(dict.fromkeys(warnings)),
        )
        self.client.heartbeat(revision, health)
        self._last_heartbeat = time.monotonic()

    def _maybe_heartbeat(self) -> None:
        if time.monotonic() - self._last_heartbeat >= self.settings.heartbeat_seconds:
            self.heartbeat()

    # ---------------------------------------------------------------- commands
    def _run_command(self, lease: WorkerCommandLease) -> None:
        command = lease.command
        try:
            self.client.ack(
                command_id=command.command_id,
                lease_token=lease.lease_token,
                lease_generation=lease.lease_generation,
                message="real worker accepted command",
            )
        except WorkerClientError as exc:
            if "409" in str(exc):
                logger.warning("command was terminal before ack", extra={"command_id": command.command_id})
                return
            logger.exception("command ack failed", extra={"command_id": command.command_id})
            return
        try:
            completion = self.executor.execute(lease)
            self.client.complete(command_id=command.command_id, completion=completion)
            self.processed += 1
            self._save_snapshot_state()
            logger.info(
                "real command completed",
                extra={
                    "command_id": command.command_id,
                    "command_type": command.command_type.value,
                    "outcome": completion.outcome.value,
                },
            )
        except Exception:
            logger.exception("real command execution failed", extra={"command_id": command.command_id})

    def _finish_future(self) -> None:
        if self._future is None:
            return
        if not self._future.done():
            return
        try:
            self._future.result()
        except Exception:
            logger.exception("background command failed")
        self._future = None

    def _is_lifecycle(self, lease: WorkerCommandLease) -> bool:
        return lease.command.command_type in {CommandType.PAUSE, CommandType.CANCEL}

    def process_lease_sync(self, lease: WorkerCommandLease) -> bool:
        try:
            self._run_command(lease)
        except Exception:
            logger.exception("synchronous command failed")
            return False
        return True

    def run_once(self) -> int:
        self._finish_future()
        self._maybe_heartbeat()
        response = self.client.poll(max_commands=1)
        count = 0
        for lease in response.leases:
            if self.process_lease_sync(lease):
                count += 1
        self._maybe_heartbeat()
        return count

    # ------------------------------------------------------------------- loop
    def run(self, stop_event: Event | None = None) -> int:
        stop_event = stop_event or self._stop
        self.ensure_enrolled()
        self.recover()
        self.sync_snapshot()
        self.heartbeat()
        iterations = 0
        limit = self.settings.max_iterations
        logger.info(
            "real worker starting",
            extra={
                "worker_id": self.settings.worker_id,
                "controller": self.settings.controller_url,
                "snapshot_revision": (
                    self.executor.current_snapshot().revision  # type: ignore[union-attr]
                    if self.executor.current_snapshot()
                    else 0
                ),
            },
        )
        while not stop_event.is_set():
            if limit is not None and iterations >= limit:
                break
            iterations += 1
            self._finish_future()
            try:
                response = self.client.poll(max_commands=1)
            except WorkerClientError:
                logger.exception("worker poll failed")
                response = None
            if response is not None:
                for lease in response.leases:
                    if self._is_lifecycle(lease):
                        self._run_command(lease)
                    elif self._future is None:
                        self._future = self._pool.submit(self._run_command, lease)
                    else:
                        logger.warning(
                            "worker busy; command lease left to expire and retry",
                            extra={"command_id": lease.command.command_id},
                        )
            self._maybe_heartbeat()
            if self._future is None:
                stop_event.wait(self.settings.poll_seconds)
        with self.executor._lock:
            for event in self.executor._active.values():
                event.set()
        if self._future is not None:
            try:
                self._future.result(timeout=min(60, self.settings.command_grace_seconds + 10))
            except Exception:
                logger.warning("background command did not stop before worker exit", exc_info=True)
        self._pool.shutdown(wait=False, cancel_futures=False)
        try:
            self.heartbeat()
        except Exception:
            logger.warning("final heartbeat failed", exc_info=True)
        logger.info("real worker stopped", extra={"processed": self.processed})
        return self.processed

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.client.close()


def print_once_summary(worker: RealWorker) -> None:
    snapshot = worker.executor.current_snapshot()
    print(
        json.dumps(
            {
                "worker_id": worker.settings.worker_id,
                "processed": worker.processed,
                "snapshot_revision": snapshot.revision if snapshot else None,
                "simulated": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
