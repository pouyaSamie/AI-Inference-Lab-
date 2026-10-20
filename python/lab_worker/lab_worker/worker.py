"""Simulated worker loop exercising the durable outbound command protocol."""

from __future__ import annotations

import logging
import time
from threading import Event
from typing import Any

from lab_core import WorkerCommandLease

from .client import WorkerClient, WorkerClientError
from .config import WorkerSettings
from .executor import SimulatedExecutor
from .inventory import build_snapshot

logger = logging.getLogger(__name__)


class SimulatedWorker:
    def __init__(
        self,
        settings: WorkerSettings,
        *,
        client: WorkerClient | None = None,
        executor: SimulatedExecutor | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or WorkerClient(settings)
        self.executor = executor or SimulatedExecutor(settings, revision=self._next_revision())
        self._last_heartbeat = 0.0
        self.processed = 0

    def _state(self) -> dict[str, Any]:
        return self.client._load_state()

    def _next_revision(self) -> int:
        try:
            state = self.client._load_state()
        except Exception:
            state = {}
        return max(1, int(state.get("snapshot_revision", 0)) + 1)

    def _save_snapshot_state(self) -> None:
        self.client.save_state(
            snapshot_revision=self.executor.snapshot.revision,
            worker_id=self.settings.worker_id,
        )

    def ensure_enrolled(self) -> None:
        if self.client.token:
            return
        if not self.settings.enrollment_token:
            raise WorkerClientError("no worker token is available and no enrollment token was configured")
        try:
            self.client.register()
            logger.info("worker enrolled", extra={"worker_id": self.settings.worker_id})
        except WorkerClientError as exc:
            if "409" in str(exc):
                raise WorkerClientError(
                    "worker_id is already enrolled; pass its token with --worker-token "
                    "or delete the stale enrollment"
                ) from exc
            raise

    def sync_snapshot(self) -> None:
        for _ in range(5):
            try:
                response = self.client.upload_snapshot(self.executor.snapshot)
                self._save_snapshot_state()
                logger.info(
                    "worker snapshot uploaded",
                    extra={
                        "worker_id": self.settings.worker_id,
                        "revision": response.get("revision"),
                    },
                )
                return
            except WorkerClientError as exc:
                if "409" not in str(exc):
                    raise
                self.executor.snapshot = build_snapshot(self.settings, self.executor.snapshot.revision + 1)
        raise WorkerClientError("could not upload a monotonic worker snapshot after 5 attempts")

    def heartbeat(self) -> None:
        self.client.heartbeat(self.executor.snapshot.revision)
        self._last_heartbeat = time.monotonic()

    def _maybe_heartbeat(self) -> None:
        if time.monotonic() - self._last_heartbeat >= self.settings.heartbeat_seconds:
            self.heartbeat()

    def process_lease(self, lease: WorkerCommandLease) -> bool:
        command = lease.command
        try:
            self.client.ack(
                command_id=command.command_id,
                lease_token=lease.lease_token,
                lease_generation=lease.lease_generation,
            )
        except WorkerClientError as exc:
            if "409" in str(exc):
                logger.warning(
                    "command was already terminal before ack",
                    extra={"command_id": command.command_id},
                )
                return False
            raise
        completion = self.executor.execute(lease)
        try:
            self.client.complete(command_id=command.command_id, completion=completion)
        except WorkerClientError:
            logger.exception("command completion failed", extra={"command_id": command.command_id})
            return False
        self.processed += 1
        self._save_snapshot_state()
        logger.info(
            "command executed",
            extra={
                "command_id": command.command_id,
                "command_type": command.command_type.value,
                "outcome": completion.outcome.value,
            },
        )
        return True

    def run_once(self) -> int:
        self._maybe_heartbeat()
        response = self.client.poll()
        count = 0
        for lease in response.leases:
            if self.process_lease(lease):
                count += 1
        self._maybe_heartbeat()
        return count

    def run(self, stop_event: Event | None = None) -> int:
        stop_event = stop_event or Event()
        self.ensure_enrolled()
        self.sync_snapshot()
        self.heartbeat()
        iterations = 0
        limit = self.settings.max_iterations
        logger.info(
            "simulated worker starting",
            extra={
                "worker_id": self.settings.worker_id,
                "controller": self.settings.controller_url,
                "snapshot_revision": self.executor.snapshot.revision,
            },
        )
        while not stop_event.is_set():
            if limit is not None and iterations >= limit:
                break
            iterations += 1
            try:
                processed = self.run_once()
            except WorkerClientError:
                logger.exception("worker poll failed")
                processed = 0
            except Exception:
                logger.exception("worker iteration failed")
                processed = 0
            if processed == 0:
                stop_event.wait(self.settings.poll_seconds)
        try:
            self.heartbeat()
        except Exception:
            logger.warning("final heartbeat failed", exc_info=True)
        logger.info("simulated worker stopped", extra={"processed": self.processed})
        return self.processed
