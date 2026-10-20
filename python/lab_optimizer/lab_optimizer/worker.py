"""Supervised optimizer loop: heartbeat, poll, execute, complete."""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from threading import Event
from typing import Any

from lab_core.errors import LabError

from lab_core import (
    OptimizerCompletion,
    OptimizerHeartbeat,
    OptimizerRequestLease,
)

from .client import ControllerClient, ControllerClientError
from .config import OptimizerSettings
from .engine import OptimizerEngineError, OptunaEngine

logger = logging.getLogger(__name__)


class OptimizerWorker:
    def __init__(
        self,
        settings: OptimizerSettings,
        *,
        engine: OptunaEngine | None = None,
        client: ControllerClient | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine or OptunaEngine(settings.db_url)
        self.client = client or ControllerClient(
            settings.controller_url,
            settings.token.get_secret_value(),
        )
        self.optimizer_id = settings.resolved_optimizer_id()
        self.started_at = datetime.now(UTC)
        self._last_heartbeat = 0.0
        self.processed = 0

    def heartbeat(self, status: str = "ready") -> None:
        heartbeat = OptimizerHeartbeat(
            optimizer_id=self.optimizer_id,
            pid=os.getpid(),
            started_at=self.started_at,
            last_seen_at=datetime.now(UTC),
            version=self.settings.version,
            status=status,
            studies_open=self.engine.open_study_count(),
        )
        self.client.heartbeat(heartbeat)
        self._last_heartbeat = time.monotonic()

    def _maybe_heartbeat(self) -> None:
        if time.monotonic() - self._last_heartbeat >= self.settings.heartbeat_seconds:
            self.heartbeat()

    def process_lease(self, lease: OptimizerRequestLease) -> bool:
        request = lease.request
        try:
            result = self.engine.dispatch(request.kind, request.payload)
            completion = OptimizerCompletion(
                optimizer_id=self.optimizer_id,
                lease_token=lease.lease_token,
                result=result,
            )
        except (OptimizerEngineError, LabError, ValueError) as exc:
            logger.exception("optimizer request failed", extra={"request_id": request.request_id})
            completion = OptimizerCompletion(
                optimizer_id=self.optimizer_id,
                lease_token=lease.lease_token,
                error_code=getattr(exc, "code", "OPTIMIZER_ENGINE_ERROR"),
                error_message=str(exc)[:2000],
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("unexpected optimizer failure", extra={"request_id": request.request_id})
            completion = OptimizerCompletion(
                optimizer_id=self.optimizer_id,
                lease_token=lease.lease_token,
                error_code="OPTIMIZER_INTERNAL_ERROR",
                error_message=f"{type(exc).__name__}: {exc}"[:2000],
            )
        try:
            self.client.complete(request.request_id, completion)
            self.processed += 1
            return True
        except ControllerClientError:
            logger.exception("failed to post optimizer completion", extra={"request_id": request.request_id})
            return False

    def run_once(self) -> int:
        self._maybe_heartbeat()
        polled = self.client.poll(self.settings.poll_max_requests, self.optimizer_id)
        count = 0
        for lease in polled.leases:
            if self.process_lease(lease):
                count += 1
        self._maybe_heartbeat()
        return count

    def run(self, stop_event: Event | None = None, max_iterations: int | None = None) -> int:
        stop_event = stop_event or Event()
        iterations = 0
        limit = max_iterations or self.settings.max_iterations
        self.heartbeat("starting")
        try:
            while not stop_event.is_set():
                if limit is not None and iterations >= limit:
                    break
                iterations += 1
                try:
                    processed = self.run_once()
                except ControllerClientError:
                    logger.exception("controller poll failed")
                    processed = 0
                except Exception:
                    logger.exception("optimizer loop iteration failed")
                    processed = 0
                if processed == 0:
                    stop_event.wait(self.settings.poll_seconds)
        finally:
            try:
                self.heartbeat("stopping")
            except Exception:
                logger.warning("failed to send final optimizer heartbeat", exc_info=True)
        return self.processed

    def health(self) -> dict[str, Any]:
        result = self.engine.health()
        result.update(
            {
                "optimizer_id": self.optimizer_id,
                "controller_url": self.settings.controller_url,
                "processed": self.processed,
            }
        )
        return result
