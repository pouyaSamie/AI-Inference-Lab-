"""Lease recovery, idempotent completions and worker protocol invariants."""

from __future__ import annotations

from datetime import timedelta

import pytest
from lab_api.services.commands import (
    complete_command,
    enqueue_command,
    expire_stale_leases,
    poll_commands,
)
from lab_core.base import utcnow
from lab_core.errors import ConflictError
from lab_worker.config import WorkerSettings
from lab_worker.worker import SimulatedWorker

from lab_core import CommandStatus, CommandType, ScanPayload
from tests.conftest import ControllerHandle


def _worker(controller: ControllerHandle, tmp_path, worker_id: str = "sim-lease") -> SimulatedWorker:
    settings = WorkerSettings(
        controller_url=controller.base_url,
        enrollment_token="test-enrollment-token-0000000000",
        worker_id=worker_id,
        state_file=str(tmp_path / f"{worker_id}-state.json"),
    )
    worker = SimulatedWorker(settings)
    worker.ensure_enrolled()
    worker.sync_snapshot()
    return worker


def test_expired_lease_is_requeued_with_new_generation(controller: ControllerHandle, tmp_path) -> None:
    worker = _worker(controller, tmp_path)
    try:
        with controller.session_factory() as session:
            row = enqueue_command(
                session,
                controller.settings,
                worker_id="sim-lease",
                command_type=CommandType.SCAN,
                payload=ScanPayload(roots=("/home/pouya/ai-lab/models",), reason="lease test"),
                idempotency_key="lease-test-scan",
            )
            session.commit()
            command_id = row.command_id

            first = poll_commands(session, controller.settings, worker_id="sim-lease", max_commands=1)
            assert len(first.leases) == 1
            lease = first.leases[0]
            assert lease.lease_generation == 1

            row = session.get(type(row), command_id)
            assert row is not None
            row.lease_expires_at = utcnow() - timedelta(seconds=1)
            session.commit()
            assert expire_stale_leases(session, controller.settings) == 1
            session.commit()

            second = poll_commands(session, controller.settings, worker_id="sim-lease", max_commands=1)
            assert len(second.leases) == 1
            assert second.leases[0].lease_generation == 2
            assert second.leases[0].lease_token != lease.lease_token
    finally:
        worker.client.close()


def test_completion_replay_is_idempotent_and_conflicts_are_explicit(
    controller: ControllerHandle, tmp_path
) -> None:
    worker = _worker(controller, tmp_path, "sim-complete")
    try:
        with controller.session_factory() as session:
            row = enqueue_command(
                session,
                controller.settings,
                worker_id="sim-complete",
                command_type=CommandType.SCAN,
                payload=ScanPayload(roots=("/home/pouya/ai-lab/models",), reason="completion test"),
                idempotency_key="completion-test-scan",
            )
            session.commit()
            polled = poll_commands(session, controller.settings, worker_id="sim-complete", max_commands=1)
            lease = polled.leases[0]
            worker.executor.snapshot = worker.executor.snapshot.model_copy(
                update={"revision": worker.executor.snapshot.revision + 1}
            )
            completion = worker.executor.execute(lease)
            assert completion.outcome is CommandStatus.COMPLETED
            _, replay = complete_command(
                session,
                controller.settings,
                worker_id="sim-complete",
                command_id=row.command_id,
                completion=completion,
            )
            assert replay is False
            _, replay = complete_command(
                session,
                controller.settings,
                worker_id="sim-complete",
                command_id=row.command_id,
                completion=completion,
            )
            assert replay is True

            replacement = (
                worker.executor.execute(
                    poll_commands(
                        session, controller.settings, worker_id="sim-complete", max_commands=1
                    ).leases[0]
                )
                if False
                else completion.model_copy(
                    update={
                        "result": completion.result.model_copy(
                            update={
                                "snapshot": completion.result.snapshot.model_copy(update={"revision": 99})
                            }
                        )
                    }
                )
            )
            with pytest.raises(ConflictError):
                complete_command(
                    session,
                    controller.settings,
                    worker_id="sim-complete",
                    command_id=row.command_id,
                    completion=replacement,
                )
    finally:
        worker.client.close()


def test_wrong_worker_cannot_complete_command(controller: ControllerHandle, tmp_path) -> None:
    worker = _worker(controller, tmp_path, "sim-owner")
    try:
        with controller.session_factory() as session:
            row = enqueue_command(
                session,
                controller.settings,
                worker_id="sim-owner",
                command_type=CommandType.SCAN,
                payload=ScanPayload(roots=("/tmp",), reason="ownership"),
                idempotency_key="ownership-scan",
            )
            session.commit()
            lease = poll_commands(session, controller.settings, worker_id="sim-owner", max_commands=1).leases[
                0
            ]
            completion = worker.executor.execute(lease)
            with pytest.raises(Exception, match="not found"):
                complete_command(
                    session,
                    controller.settings,
                    worker_id="another-worker",
                    command_id=row.command_id,
                    completion=completion,
                )
    finally:
        worker.client.close()


def test_lease_renewal_extends_same_generation_and_rejects_bad_token(
    controller: ControllerHandle, tmp_path
) -> None:
    worker = _worker(controller, tmp_path, "sim-renew")
    try:
        with controller.session_factory() as session:
            row = enqueue_command(
                session,
                controller.settings,
                worker_id="sim-renew",
                command_type=CommandType.SCAN,
                payload=ScanPayload(roots=("/home/pouya/ai-lab/models",), reason="renew test"),
                idempotency_key="renew-test-scan",
            )
            session.commit()
            command_id = row.command_id
        polled = worker.client.poll()
        assert len(polled.leases) == 1
        lease = polled.leases[0]
        before = lease.lease_expires_at
        renewed = worker.client.renew(
            command_id=command_id,
            lease_token=lease.lease_token,
            lease_generation=lease.lease_generation,
            extend_seconds=300,
        )
        assert renewed["lease_generation"] == lease.lease_generation
        assert renewed["command_id"] == command_id
        assert renewed["lease_expires_at"] != before.isoformat()
        with pytest.raises(Exception, match="409"):
            worker.client.renew(
                command_id=command_id,
                lease_token="wrong-token",
                lease_generation=lease.lease_generation,
                extend_seconds=300,
            )
    finally:
        worker.client.close()
