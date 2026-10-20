"""End-to-end API flow with the explicit Phase 1 simulated lane."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from tests.conftest import ControllerHandle, plan_body

TERMINAL = {"completed", "failed", "blocked", "cancelled"}


async def _stream_events(
    controller: ControllerHandle, experiment_id: str, *, last_event_id: int
) -> list[str]:
    from lab_api.services.sse import event_stream

    class FakeRequest:
        async def is_disconnected(self) -> bool:
            return False

    events: list[str] = []
    stream = event_stream(
        FakeRequest(),
        controller.settings,
        controller.session_factory,
        experiment_id,
        last_event_id=last_event_id,
    )
    async for chunk in stream:
        for line in chunk.splitlines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
        if len(events) >= 2 or (events and events[0] == "snapshot"):
            break
    return events


def test_plan_create_optimize_and_reject_simulated_recipe(
    controller: ControllerHandle,
    simulated_worker,
    optimizer,
) -> None:
    headers = controller.operator_headers
    with httpx.Client(base_url=controller.base_url, headers=headers, timeout=10.0) as client:
        plan_response = client.post("/api/v1/experiments/plan", json=plan_body(max_candidates=3))
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()["plan"]
        assert plan["warnings"]
        assert "PHASE_1_SIMULATED_EXECUTION" in plan["warnings"]

        create_response = client.post(
            "/api/v1/experiments",
            headers={"Idempotency-Key": "create-e2e-1"},
            json={"plan": plan},
        )
        assert create_response.status_code == 201, create_response.text
        experiment = create_response.json()
        experiment_id = experiment["status"]["experiment_id"]

        deadline = time.monotonic() + 30
        view: dict = experiment
        while time.monotonic() < deadline:
            view = client.get(f"/api/v1/experiments/{experiment_id}").json()
            if view["status"]["state"] in TERMINAL:
                break
            time.sleep(0.1)
        else:
            pytest.fail(f"experiment did not finish: {view['status']}")

        assert view["status"]["state"] == "completed", view["status"]
        assert view["simulation"] is True
        assert view["candidates"]
        assert view["observations"]
        assert all(item["simulated"] is True for item in view["observations"])
        assert all(item["measurement_status"] == "simulated" for item in view["observations"])

        results = client.get(f"/api/v1/experiments/{experiment_id}/results")
        assert results.status_code == 200, results.text
        result_body = results.json()
        assert result_body["simulated"] is True
        assert result_body["best_candidate_id"]

        recipe = client.post(
            "/api/v1/recipes",
            headers={"Idempotency-Key": "recipe-e2e-1"},
            json={
                "experiment_id": experiment_id,
                "candidate_id": result_body["best_candidate_id"],
            },
        )
        assert recipe.status_code == 409, recipe.text
        assert "simulated evidence" in recipe.text

        replay = client.post(
            "/api/v1/experiments",
            headers={"Idempotency-Key": "create-e2e-1"},
            json={"plan": plan},
        )
        assert replay.status_code == 200
        assert replay.headers["Idempotent-Replayed"] == "true"
        assert replay.json()["status"]["experiment_id"] == experiment_id

        conflict = client.post(
            "/api/v1/experiments",
            headers={"Idempotency-Key": "create-e2e-1"},
            json={"plan": plan, "notes": ["different body"]},
        )
        assert conflict.status_code == 409

        page = client.get(f"/api/v1/experiments/{experiment_id}/events/page")
        assert page.status_code == 200
        event_types = {event["type"] for event in page.json()["events"]}
        assert "experiment.created" in event_types
        assert "experiment.completed" in event_types
        assert page.json()["last_event_id"] > 0

        assert asyncio.run(_stream_events(controller, experiment_id, last_event_id=0))[0] == "snapshot"

        with controller.session_factory() as session:
            from lab_api.events import latest_sequence, set_replay_floor

            floor = latest_sequence(session, experiment_id)
            assert floor > 1
            set_replay_floor(session, experiment_id, floor)
            session.commit()
        gap_events = asyncio.run(_stream_events(controller, experiment_id, last_event_id=1))
        assert gap_events[0] == "event.gap"
        assert gap_events[1] == "snapshot"


def test_plan_requires_preflight_for_missing_inventory(controller: ControllerHandle) -> None:
    from lab_worker.client import WorkerClient
    from lab_worker.config import WorkerSettings

    with httpx.Client(
        base_url=controller.base_url, headers=controller.operator_headers, timeout=10.0
    ) as client:
        worker_settings = WorkerSettings(
            controller_url=controller.base_url,
            enrollment_token="test-enrollment-token-0000000000",
            worker_id="sim-no-snapshot",
            state_file=f"{controller.settings.artifact_root}/no-snapshot-state.json",
        )
        with WorkerClient(worker_settings) as worker_client:
            response = worker_client.register()
            assert response["token"]
            plan_response = client.post(
                "/api/v1/experiments/plan",
                json={
                    **plan_body(),
                    "worker_id": "sim-no-snapshot",
                    "gpu_uuids": ["sim-GPU-0"],
                },
            )
        assert plan_response.status_code == 202, plan_response.text
        body = plan_response.json()
        assert body["status"] == "preflight_required"
        assert "NO_SNAPSHOT" in body["reason"]
        assert body["command_id"]
        commands = client.get("/api/v1/workers/sim-no-snapshot/commands")
        assert commands.status_code == 200
        assert commands.json()[0]["command_type"] == "SCAN"


def test_stale_snapshot_returns_typed_preflight_required(controller: ControllerHandle, tmp_path) -> None:
    from datetime import timedelta

    from lab_api.orm import WorkerRow
    from lab_core.base import utcnow
    from lab_worker.config import WorkerSettings
    from lab_worker.worker import SimulatedWorker

    worker_settings = WorkerSettings(
        controller_url=controller.base_url,
        enrollment_token="test-enrollment-token-0000000000",
        worker_id="sim-stale",
        state_file=str(tmp_path / "stale-worker-state.json"),
    )
    worker = SimulatedWorker(worker_settings)
    try:
        worker.ensure_enrolled()
        worker.sync_snapshot()
    finally:
        worker.client.close()

    with controller.session_factory() as session:
        row = session.get(WorkerRow, "sim-stale")
        assert row is not None
        row.last_heartbeat_at = utcnow() - timedelta(days=2)
        session.commit()

    with httpx.Client(
        base_url=controller.base_url, headers=controller.operator_headers, timeout=10.0
    ) as client:
        response = client.post(
            "/api/v1/experiments/plan",
            json={**plan_body(), "worker_id": "sim-stale"},
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "preflight_required"
    assert "WORKER_OFFLINE" in body["reason"]


def test_execution_mode_rejects_real_mode_startup(settings) -> None:
    from lab_api.app import create_app

    real = settings.model_copy(update={"execution_mode": "real"})
    with pytest.raises(ValueError, match="real execution"):
        create_app(real)
