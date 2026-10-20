"""Background reconciliation scheduler.

This loop never performs Optuna work. It expires leases, reconciles in-flight
studies, and writes durable optimizer/worker commands. It is intentionally
idempotent so a controller restart can safely replay it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from lab_core.errors import LabError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from lab_core import TERMINAL_JOB_STATES

from ..config import Settings
from ..db import session_scope
from ..orm import ExperimentRow, StudyRow
from .commands import expire_stale_leases
from .inventory import mark_workers_offline
from .optimizer_queue import expire_optimizer_leases, reconcile_study

logger = logging.getLogger(__name__)


class RuntimeScheduler:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if not self.settings.scheduler_enabled or self.running:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="lab-controller-scheduler")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                self.tick()
            except Exception:  # pragma: no cover - logged, scheduler survives
                logger.exception("scheduler tick failed")
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=self.settings.scheduler_interval_seconds,
                )
            except TimeoutError:
                continue

    def tick(self) -> None:
        with session_scope(self.session_factory) as session:
            mark_workers_offline(session, self.settings)
            expire_stale_leases(session, self.settings)
            expire_optimizer_leases(session, self.settings)
            terminal = [state.value for state in TERMINAL_JOB_STATES]
            studies = session.scalars(
                select(StudyRow)
                .join(ExperimentRow, ExperimentRow.experiment_id == StudyRow.experiment_id)
                .where(
                    ExperimentRow.state.not_in(terminal),
                    ExperimentRow.preflight_passed.is_(True),
                    ExperimentRow.paused.is_(False),
                )
            ).all()
            for study in studies:
                try:
                    reconcile_study(session, self.settings, study)
                except LabError:
                    logger.exception("study reconciliation rejected", extra={"study_id": study.study_id})
            session.flush()
