"""Offline regressions from the installed desktop's real user journey."""

from datetime import timedelta

import httpx
import pytest
from lab_api.orm import WorkerCommandRow
from lab_api.services.commands import (
    ack_command,
    complete_command,
    enqueue_command,
    expire_stale_leases,
    poll_commands,
)
from lab_core.errors import ConflictError

from lab_core import (
    AckDisposition,
    CancelPayload,
    CommandAck,
    CommandCompletion,
    CommandFailure,
    CommandStatus,
    CommandType,
    FailureKind,
    ScanPayload,
    utcnow,
)
from tests.conftest import plan_body
from tests.test_resilience import _worker


@pytest.mark.parametrize("kind", [CommandType.RUN_RECIPE, CommandType.RECIPE_CHAT])
def test_interactive_leases_expire_without_automatic_reexecution(controller, tmp_path, kind):
    worker = _worker(controller, tmp_path, "sim-interactive-expiry")
    try:
        with controller.session_factory() as session:
            row = WorkerCommandRow(
                command_id=f"expiry-{kind.value}",
                worker_id="sim-interactive-expiry",
                command_type=kind.value,
                payload_json={},
                idempotency_key=f"expiry-{kind.value}",
                status="acknowledged",
                attempts=1,
                lease_generation=1,
                lease_expires_at=utcnow() - timedelta(seconds=1),
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(row)
            session.commit()
            assert expire_stale_leases(session, controller.settings) == 1
            session.commit()
            session.refresh(row)
            assert row.status == "expired"
            assert row.failure_json["kind"] == "TIMEOUT"
            assert row.last_error == "interactive request expired; retry explicitly"
    finally:
        worker.client.close()


def _create(controller, worker_id):
    body = {**plan_body(), "worker_id": worker_id}
    with httpx.Client(base_url=controller.base_url, headers=controller.operator_headers) as client:
        response = client.post("/api/v1/experiments/plan", json=body)
        assert response.status_code == 200, response.text
        created = client.post(
            "/api/v1/experiments",
            json={"plan": response.json()["plan"]},
            headers={"Idempotency-Key": f"regression-{worker_id}"},
        )
        assert created.status_code == 201, created.text
        return created.json()["status"]["experiment_id"]


@pytest.mark.parametrize("outcome", ["failed", "rejected", "expired"])
def test_preflight_transport_failure_blocks_and_can_retry(controller, tmp_path, outcome):
    worker_id = f"sim-{outcome}"
    worker = _worker(controller, tmp_path, worker_id)
    try:
        experiment_id = _create(controller, worker_id)
        with controller.session_factory() as session:
            lease = poll_commands(session, controller.settings, worker_id=worker_id, max_commands=1).leases[0]
            assert lease.command.command_type is CommandType.PREFLIGHT
            row = session.get(WorkerCommandRow, lease.command.command_id)
            if outcome == "expired":
                row.attempts = controller.settings.command_max_attempts
                row.lease_expires_at = utcnow() - timedelta(seconds=1)
                session.commit()
                expire_stale_leases(session, controller.settings)
                session.commit()
            elif outcome == "rejected":
                ack_command(
                    session,
                    controller.settings,
                    worker_id=worker_id,
                    command_id=row.command_id,
                    ack=CommandAck(
                        lease_token=lease.lease_token,
                        lease_generation=lease.lease_generation,
                        disposition=AckDisposition.REJECTED,
                        message="not supported",
                    ),
                )
            else:
                completion = CommandCompletion(
                    worker_id=worker_id,
                    lease_token=lease.lease_token,
                    lease_generation=lease.lease_generation,
                    outcome=CommandStatus.FAILED,
                    failure=CommandFailure(
                        kind=FailureKind.UNKNOWN, message="ExecutableTrustError: executable not registered"
                    ),
                )
                _, replay = complete_command(
                    session,
                    controller.settings,
                    worker_id=worker_id,
                    command_id=row.command_id,
                    completion=completion,
                )
                assert not replay
                _, replay = complete_command(
                    session,
                    controller.settings,
                    worker_id=worker_id,
                    command_id=row.command_id,
                    completion=completion,
                )
                assert replay
                with pytest.raises(ConflictError):
                    complete_command(
                        session,
                        controller.settings,
                        worker_id=worker_id,
                        command_id=row.command_id,
                        completion=completion.model_copy(
                            update={"failure": CommandFailure(message="different failure")}
                        ),
                    )
        with httpx.Client(base_url=controller.base_url, headers=controller.operator_headers) as client:
            status = client.get(f"/api/v1/experiments/{experiment_id}").json()["status"]
            assert status["state"] == "blocked"
            assert status["error_code"].startswith("PREFLIGHT_")
            assert "retry preflight" in status["error_message"]
            retry = client.post(f"/api/v1/experiments/{experiment_id}/preflight/retry")
            assert retry.status_code == 200, retry.text
            assert retry.json()["completed_at"] is None
            cancelled = client.post(f"/api/v1/experiments/{experiment_id}/cancel")
            assert cancelled.status_code == 200
            if outcome == "failed":
                with controller.session_factory() as session:
                    _, replay = complete_command(
                        session,
                        controller.settings,
                        worker_id=worker_id,
                        command_id=lease.command.command_id,
                        completion=completion,
                    )
                    assert replay
            assert client.get(f"/api/v1/experiments/{experiment_id}").json()["status"]["state"] == "cancelled"
    finally:
        worker.client.close()


def test_busy_worker_does_not_lease_more_execution_but_can_cancel(controller, tmp_path):
    worker_id = "sim-busy"
    worker = _worker(controller, tmp_path, worker_id)
    try:
        with controller.session_factory() as session:
            first = enqueue_command(
                session,
                controller.settings,
                worker_id=worker_id,
                command_type=CommandType.SCAN,
                payload=ScanPayload(roots=()),
                idempotency_key="busy-first",
            )
            second = enqueue_command(
                session,
                controller.settings,
                worker_id=worker_id,
                command_type=CommandType.SCAN,
                payload=ScanPayload(roots=()),
                idempotency_key="busy-second",
            )
            session.commit()
            leased = poll_commands(session, controller.settings, worker_id=worker_id, max_commands=8)
            assert len(leased.leases) == 1
            assert leased.leases[0].command.command_id == first.command_id
            assert not poll_commands(session, controller.settings, worker_id=worker_id).leases
            session.refresh(second)
            assert second.attempts == 0 and second.status == "pending"
            cancel = enqueue_command(
                session,
                controller.settings,
                worker_id=worker_id,
                command_type=CommandType.CANCEL,
                payload=CancelPayload(experiment_id="unused-test-id"),
                idempotency_key="busy-cancel",
            )
            session.commit()
            assert (
                poll_commands(session, controller.settings, worker_id=worker_id).leases[0].command.command_id
                == cancel.command_id
            )
    finally:
        worker.client.close()
