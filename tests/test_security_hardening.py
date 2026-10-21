"""Phase 8 security regression coverage for credential scoping and revocation."""

from __future__ import annotations

from pathlib import Path

import httpx
from lab_api.orm import WorkerRow
from lab_worker.client import WorkerClient
from lab_worker.config import WorkerSettings

from tests.conftest import ENROLLMENT_TOKEN, OPTIMIZER_TOKEN, ControllerHandle

WORKER_ID = "security-worker"


def _enroll(controller: ControllerHandle, tmp_path: Path) -> str:
    settings = WorkerSettings(
        controller_url=controller.base_url,
        enrollment_token=ENROLLMENT_TOKEN,
        worker_id=WORKER_ID,
        worker_name="security test worker",
        state_file=str(tmp_path / "security-worker-state.json"),
    )
    with WorkerClient(settings) as client:
        response = client.register()
    token = str(response["token"])
    assert token
    return token


def test_public_health_but_all_operator_routes_require_a_bearer(controller: ControllerHandle) -> None:
    with httpx.Client(base_url=controller.base_url, timeout=10) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        for path in (
            "/api/v1/status",
            "/api/v1/workers",
            "/api/v1/experiments",
            "/api/v1/recipes",
            "/api/v1/releases",
            "/api/v1/comparisons",
        ):
            response = client.get(path)
            assert response.status_code == 401, (path, response.text)

        bearer = client.get(
            "/api/v1/status",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert bearer.status_code == 401
        assert "dXNlcjpwYXNz" not in bearer.text


def test_credentials_are_scoped_to_their_protocol(controller: ControllerHandle, tmp_path: Path) -> None:
    worker_token = _enroll(controller, tmp_path)
    worker_headers = {"Authorization": f"Bearer {worker_token}"}
    with httpx.Client(base_url=controller.base_url, timeout=10) as client:
        assert client.get("/api/v1/status", headers=worker_headers).status_code == 403
        assert client.get("/api/v1/workers", headers=worker_headers).status_code == 403
        assert (
            client.post(
                f"/api/v1/workers/{WORKER_ID}/commands/poll",
                headers=controller.operator_headers,
                json={"max_commands": 1},
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/v1/status",
                headers={"Authorization": f"Bearer {OPTIMIZER_TOKEN}"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/workers/register",
                headers={"X-Enrollment-Token": "wrong-enrollment-token"},
                json={},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/workers/register",
                headers=controller.operator_headers,
                json={},
            ).status_code
            == 401
        )


def test_disabled_worker_token_cannot_poll_heartbeat_or_read_snapshot(
    controller: ControllerHandle, tmp_path: Path
) -> None:
    worker_token = _enroll(controller, tmp_path)
    with controller.session_factory() as session:
        row = session.get(WorkerRow, WORKER_ID)
        assert row is not None
        row.disabled = True
        session.commit()

    headers = {"Authorization": f"Bearer {worker_token}"}
    with httpx.Client(base_url=controller.base_url, timeout=10) as client:
        assert (
            client.post(
                f"/api/v1/workers/{WORKER_ID}/commands/poll",
                headers=headers,
                json={"max_commands": 1},
            ).status_code
            == 401
        )
        assert (
            client.post(
                f"/api/v1/workers/{WORKER_ID}/heartbeat",
                headers=headers,
                json={"snapshot_revision": 0},
            ).status_code
            == 401
        )
        assert client.get(f"/api/v1/workers/{WORKER_ID}/snapshot", headers=headers).status_code == 401
