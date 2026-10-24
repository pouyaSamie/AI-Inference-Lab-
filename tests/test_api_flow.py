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
        assert any(item["role"] == "baseline" for item in view["candidates"])
        assert view["observations"]
        assert all(item["simulated"] is True for item in view["observations"])
        assert all(item["measurement_status"] == "simulated" for item in view["observations"])
        assert all(item["repetitions"] == 3 for item in view["observations"])
        assert all(len(item["samples"]) == 3 for item in view["observations"])

        snapshot = client.get("/api/v1/workers/sim-test/snapshot")
        assert snapshot.status_code == 200, snapshot.text
        assert snapshot.json()["worker_id"] == "sim-test"
        assert snapshot.json()["engines"]
        assert snapshot.json()["models"]
        missing = client.get("/api/v1/workers/missing-worker/snapshot")
        assert missing.status_code == 404

        results = client.get(f"/api/v1/experiments/{experiment_id}/results")
        assert results.status_code == 200, results.text
        result_body = results.json()
        assert result_body["simulated"] is True
        assert result_body["best_candidate_id"]
        assert result_body["validated_winner_candidate_id"] is None
        assert result_body["finalization"]["classification"] == "SIMULATED"
        assert result_body["finalization"]["per_context"][0]["winner_candidate_id"] is None

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

        # A new key means a new run, even when the immutable plan is identical.
        # Keep completed/cancelled studies intact and keep same-key replays stable.
        from lab_api.orm import StudyRow

        experiment_ids = [experiment_id]
        for key in ("repeat-completed-plan", "repeat-cancelled-plan"):
            repeated = client.post(
                "/api/v1/experiments",
                headers={"Idempotency-Key": key},
                json={"plan": plan},
            )
            assert repeated.status_code == 201, repeated.text
            repeated_id = repeated.json()["status"]["experiment_id"]
            assert repeated_id not in experiment_ids
            experiment_ids.append(repeated_id)
            replayed = client.post(
                "/api/v1/experiments",
                headers={"Idempotency-Key": key},
                json={"plan": plan},
            )
            assert replayed.status_code == 200, replayed.text
            assert replayed.headers["Idempotent-Replayed"] == "true"
            assert replayed.json()["status"]["experiment_id"] == repeated_id
            cancelled = client.post(f"/api/v1/experiments/{repeated_id}/cancel")
            assert cancelled.status_code == 200, cancelled.text
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                state = client.get(f"/api/v1/experiments/{repeated_id}").json()["status"]["state"]
                if state in TERMINAL:
                    break
                time.sleep(0.05)
            assert state == "cancelled"
        with controller.session_factory() as session:
            studies = session.query(StudyRow).filter(StudyRow.experiment_id.in_(experiment_ids)).all()
            assert len(studies) == 3
            assert len({study.study_id for study in studies}) == 3
            assert len({study.study_name for study in studies}) == 3
        assert client.get(f"/api/v1/experiments/{experiment_id}").json()["status"]["state"] == "completed"


def test_qualified_measured_evidence_builds_a_validated_recipe(
    controller: ControllerHandle,
    simulated_worker,
    optimizer,
) -> None:
    """Exercise the full gate with synthetic *measured* rows after a simulated run.

    This is still offline test data, not engine evidence. It proves that the
    controller-side qualification and recipe path can succeed when every
    required condition is present.
    """

    from lab_api.orm import CandidateRow, ObservationRow

    from lab_core import (
        BenchmarkObservation,
        CandidateRole,
        EvidenceKind,
        MeasurementStatus,
        QualityGate,
        QualityGateStatus,
        stable_id,
    )

    with httpx.Client(
        base_url=controller.base_url,
        headers=controller.operator_headers,
        timeout=10.0,
    ) as client:
        plan = client.post(
            "/api/v1/experiments/plan",
            json=plan_body(max_candidates=2),
        ).json()["plan"]
        experiment_id = client.post(
            "/api/v1/experiments",
            headers={"Idempotency-Key": "create-qualified-1"},
            json={"plan": plan},
        ).json()["status"]["experiment_id"]

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = client.get(f"/api/v1/experiments/{experiment_id}").json()["status"]
            if status["state"] in TERMINAL:
                break
            time.sleep(0.1)
        assert status["state"] == "completed", status

    with controller.session_factory() as session:
        candidate_rows = session.query(CandidateRow).filter_by(experiment_id=experiment_id).all()
        candidates = {row.candidate_id: CandidateRole(row.payload_json["role"]) for row in candidate_rows}
        observation_rows = session.query(ObservationRow).filter_by(experiment_id=experiment_id).all()
        assert len(observation_rows) == len(candidate_rows)
        observations = [BenchmarkObservation.model_validate(row.payload_json) for row in observation_rows]
        baseline = next(
            observation
            for observation in observations
            if candidates[observation.candidate_id] is CandidateRole.BASELINE
        )
        assert baseline.metrics.prefill_tokens_per_sec is not None
        assert baseline.metrics.decode_tokens_per_sec is not None
        baseline_prefill = baseline.metrics.prefill_tokens_per_sec
        baseline_decode = baseline.metrics.decode_tokens_per_sec
        for row, observation in zip(observation_rows, observations, strict=True):
            role = candidates[observation.candidate_id]
            if role is CandidateRole.CANDIDATE:
                assert len(observation.samples) == len(baseline.samples)
                metrics = observation.metrics.model_copy(
                    update={
                        "prefill_tokens_per_sec": baseline_prefill * 1.5,
                        "decode_tokens_per_sec": baseline_decode * 1.5,
                    }
                )
                samples = tuple(
                    sample.model_copy(
                        update={
                            "prefill_tokens_per_sec": baseline_sample.prefill_tokens_per_sec * 1.5,
                            "decode_tokens_per_sec": baseline_sample.decode_tokens_per_sec * 1.5,
                        }
                    )
                    for sample, baseline_sample in zip(observation.samples, baseline.samples, strict=True)
                )
            else:
                metrics = observation.metrics
                samples = observation.samples
            retained_gates = tuple(
                gate
                for gate in observation.quality_gates
                if gate.name not in {"context_truncation", "planned_prompt_tokens"}
            )
            gates = (
                *retained_gates,
                QualityGate(name="context_truncation", status=QualityGateStatus.PASSED),
                QualityGate(name="planned_prompt_tokens", status=QualityGateStatus.PASSED),
            )
            measured = observation.model_copy(
                update={
                    "observation_id": stable_id(
                        "obs",
                        observation.candidate_id,
                        observation.attempt,
                        EvidenceKind.SERVER_API.value,
                        int(observation.context),
                    ),
                    "simulated": False,
                    "evidence_kind": EvidenceKind.SERVER_API,
                    "measurement_status": MeasurementStatus.MEASURED,
                    "metrics": metrics,
                    "samples": samples,
                    "quality_gates": gates,
                }
            )
            row.simulated = False
            row.evidence_kind = EvidenceKind.SERVER_API.value
            row.measurement_status = MeasurementStatus.MEASURED.value
            row.payload_json = measured.model_dump(mode="json")
        session.commit()
        candidate_id = next(
            candidate_id for candidate_id, role in candidates.items() if role is CandidateRole.CANDIDATE
        )

    with httpx.Client(
        base_url=controller.base_url,
        headers=controller.operator_headers,
        timeout=10.0,
    ) as client:
        response = client.post(
            "/api/v1/recipes",
            headers={"Idempotency-Key": "recipe-qualified-1"},
            json={"experiment_id": experiment_id, "candidate_id": candidate_id},
        )
        assert response.status_code == 201, response.text
        recipe = response.json()
        assert recipe["status"] == "validated"
        assert recipe["recipe"]["validation"]["confidence_ref"]

        # Each HTTP request opens a fresh SQLite session, which reloads naive
        # datetimes even though the contract requires timezone-aware timestamps.
        from datetime import datetime

        recipe_id = recipe["recipe_id"]
        for response in (
            client.get(f"/api/v1/recipes/{recipe_id}"),
            client.post(
                "/api/v1/recipes",
                headers={"Idempotency-Key": "recipe-qualified-1"},
                json={"experiment_id": experiment_id, "candidate_id": candidate_id},
            ),
        ):
            assert response.status_code in {200, 201}, response.text
            assert response.json() == recipe
            assert datetime.fromisoformat(response.json()["created_at"]).tzinfo is not None
        for params in ({}, {"experiment_id": experiment_id}):
            listed = client.get("/api/v1/recipes", params=params)
            assert listed.status_code == 200, listed.text
            assert listed.json() == {"recipes": [recipe], "total": 1}

        # Queue-only serving contract checks using the same synthetic measured
        # rows. Stop the simulator first: these commands must never launch a real
        # engine or be represented as live serving acceptance.
        simulated_worker.stop.set()
        simulated_worker.thread.join(timeout=5)
        from lab_api.orm import WorkerCommandRow, WorkerRow

        from lab_core import ServingSession, utcnow

        old_mode = controller.settings.execution_mode
        controller.settings.execution_mode = "real"
        try:
            with controller.session_factory() as session:
                worker = session.get(WorkerRow, "sim-test")
                worker.roles = [*worker.roles, "recipe-serving"]
                session.commit()
            started = client.post(
                f"/api/v1/recipes/{recipe_id}/run", headers={"Idempotency-Key": "serve-qualified"}
            )
            assert started.status_code == 200, started.text
            command_id = started.json()["command_id"]
            with controller.session_factory() as session:
                command = session.get(WorkerCommandRow, command_id)
                serving_id = command.payload_json["session_id"]
                worker = session.get(WorkerRow, "sim-test")
                worker.serving_json = ServingSession(
                    session_id=serving_id,
                    recipe_id=recipe_id,
                    state="ready",
                    context_tokens=4096,
                    port=18765,
                    started_at=utcnow(),
                ).model_dump(mode="json")
                session.commit()
            replay = client.post(
                f"/api/v1/recipes/{recipe_id}/run", headers={"Idempotency-Key": "serve-qualified"}
            )
            assert replay.status_code == 200 and replay.json()["command_id"] == command_id
            duplicate = client.post(
                f"/api/v1/recipes/{recipe_id}/run", headers={"Idempotency-Key": "serve-other"}
            )
            assert duplicate.status_code == 409
            state = client.get("/api/v1/serving/sim-test")
            assert state.status_code == 200 and state.json()["session_id"] == serving_id
            benchmark = client.post(
                "/api/v1/experiments", headers={"Idempotency-Key": "while-serving"}, json={"plan": plan}
            )
            assert benchmark.status_code == 409
            body = {"session_id": serving_id, "messages": [{"role": "user", "content": "fixture"}]}
            chat = client.post(
                "/api/v1/serving/sim-test/chat", json=body, headers={"Idempotency-Key": "chat-once"}
            )
            assert chat.status_code == 200, chat.text
            again = client.post(
                "/api/v1/serving/sim-test/chat", json=body, headers={"Idempotency-Key": "chat-once"}
            )
            assert again.status_code == 200 and again.json()["command_id"] == chat.json()["command_id"]
            changed = client.post(
                "/api/v1/serving/sim-test/chat",
                json={**body, "max_tokens": 32},
                headers={"Idempotency-Key": "chat-once"},
            )
            assert changed.status_code == 409
            stopped = client.post(f"/api/v1/serving/sim-test/{serving_id}/stop")
            assert stopped.status_code == 200
            assert stopped.json()["command_type"] == "STOP_RECIPE"
        finally:
            controller.settings.execution_mode = old_mode


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


def test_execution_mode_accepts_real_mode_startup(settings) -> None:
    from lab_api.app import create_app

    real = settings.model_copy(update={"execution_mode": "real"})
    app = create_app(real)
    assert app.state.settings.execution_mode == "real"


def test_real_planning_queues_hash_verification_for_discovered_models(
    controller: ControllerHandle, simulated_worker, monkeypatch
) -> None:
    from lab_api.orm import WorkerCommandRow
    from lab_api.schemas import PlanRequest
    from lab_api.services import planning
    from lab_api.services.inventory import latest_snapshot, snapshot_model

    with controller.session_factory() as session:
        row = latest_snapshot(session, "sim-test")
        assert row is not None
        snapshot = snapshot_model(row)
        models = tuple(
            model.model_copy(
                update={
                    "files": tuple(
                        file.model_copy(update={"sha256": None, "verified": False}) for file in model.files
                    )
                }
            )
            for model in snapshot.models
        )
        monkeypatch.setattr(
            planning, "snapshot_model", lambda _: snapshot.model_copy(update={"models": models})
        )
        response = planning.build_plan(
            session,
            controller.settings.model_copy(update={"execution_mode": "real"}),
            PlanRequest.model_validate(plan_body()),
        )
        assert response.status.value == "preflight_required"
        assert response.plan is None
        assert "selected model files" in response.reason
        repeated = planning.build_plan(
            session,
            controller.settings.model_copy(update={"execution_mode": "real"}),
            PlanRequest.model_validate(plan_body()),
        )
        assert repeated.command_id == response.command_id
        command = session.get(WorkerCommandRow, response.command_id)
        assert command is not None
        assert command.payload_json["hash_models"] is True
