"""Offline Phase 7 release intelligence API flow against the simulated lane."""

from __future__ import annotations

from typing import Any

import httpx
from lab_api.orm import ReleaseAssessmentRow

from lab_core import WorkloadSuite
from tests.conftest import ControllerHandle

CANDIDATE_SHA = "b" * 64
SECOND_CANDIDATE_SHA = "c" * 64


def _snapshot(client: httpx.Client, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get("/api/v1/workers/sim-test/snapshot", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _release(
    snapshot: dict[str, Any],
    *,
    version: str = "0.7.1-test",
    build: str = "702-test",
    artifact_sha256: str | None = CANDIDATE_SHA,
    commit: str = "candidate-test",
    changed_paths: tuple[str, ...] = ("ggml/src/ggml-cuda/mmq.cu",),
) -> dict[str, Any]:
    engine = snapshot["engines"][0]["engine"]
    return {
        "engine_id": engine["engine_id"],
        "version": version,
        "build": build,
        "backend": engine["backend"],
        "executable_id": engine["executable_id"],
        "source_commit": commit,
        "artifact_sha256": artifact_sha256,
        "released_at": "2026-10-21T00:00:00Z",
        "source": "offline_import",
        "changelog": "Offline release metadata fixture; no artifact was downloaded.",
        "changed_paths": list(changed_paths),
    }


def _check(
    client: httpx.Client,
    headers: dict[str, str],
    release: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/releases/check",
        headers=headers,
        json={
            "worker_id": "sim-test",
            "model_id": "qwen2.5-7b-instruct-q4_k_m",
            "release": release,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _comparison(
    client: httpx.Client,
    headers: dict[str, str],
    checked: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/comparisons",
        headers=headers,
        json={
            "notice_id": checked["notice"]["notice_id"],
            "assessment_id": checked["assessment"]["assessment_id"],
            "contexts": [4096],
            "objective": "balanced",
            "min_improvement_pct": 5.0,
            "confidence_level": 0.95,
        },
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def _evidence(
    comparison: dict[str, Any],
    *,
    candidate_throughput: tuple[float, float] = (80.0, 40.0),
    simulated: bool = False,
) -> dict[str, Any]:
    return {
        "worker_id": comparison["worker_id"],
        "model_digest": comparison["model_digest"],
        "workload_digest": WorkloadSuite().digest(),
        "baseline_engine_sha256": comparison["baseline_engine"]["executable_sha256"],
        "candidate_engine_sha256": comparison["candidate_engine"]["executable_sha256"],
        "simulated": simulated,
        "measurement_status": "simulated" if simulated else "measured",
        "samples": [
            {
                "context": 4096,
                "baseline": {"prefill_tokens_per_sec": 100.0, "decode_tokens_per_sec": 50.0},
                "candidate": {
                    "prefill_tokens_per_sec": candidate_throughput[0],
                    "decode_tokens_per_sec": candidate_throughput[1],
                },
            }
            for _ in range(3)
        ],
    }


def test_offline_release_import_and_regression_workflow(
    controller: ControllerHandle,
    simulated_worker,
) -> None:
    headers = controller.operator_headers
    with httpx.Client(base_url=controller.base_url, timeout=10) as client:
        before = _snapshot(client, headers)
        installed = before["engines"][0]["engine"]
        release = _release(before)

        imported = _check(client, headers, release)
        assert imported["result"] == "imported"
        notice = imported["notice"]
        assessment = imported["assessment"]
        assert notice["decision"] == "pending"
        assert notice["release"]["artifact_sha256"] == CANDIDATE_SHA
        assert assessment["impact"] == "P0"
        assert assessment["applicable"] is True
        assert assessment["requires_ab"] is True
        assert assessment["recommended_action"] == "targeted_rerun"
        assert assessment["current_engine"]["executable_sha256"] == installed["executable_sha256"]
        assert assessment["candidate_engine_sha256"] == CANDIDATE_SHA
        assert assessment["model_identity_complete"] is True
        assert assessment["gpu_uuids"] == ["sim-GPU-0"]
        assert "P0_RELEASE_AREA" in assessment["reasons"]

        replay = _check(client, headers, release)
        assert replay["result"] == "reused"
        assert replay["notice"]["notice_id"] == notice["notice_id"]
        assert replay["assessment"]["assessment_id"] == assessment["assessment_id"]

        listing = client.get("/api/v1/releases", headers=headers)
        assert listing.status_code == 200
        assert listing.json()["total"] == 1

        detail = client.get(f"/api/v1/releases/{notice['notice_id']}", headers=headers)
        assert detail.status_code == 200
        assert len(detail.json()["assessments"]) == 1

        pinned = client.post(
            f"/api/v1/releases/{notice['notice_id']}/decision",
            headers=headers,
            json={"action": "pin", "note": "Keep the installed build until evidence is ready."},
        )
        assert pinned.status_code == 200
        assert pinned.json()["notice"]["decision"] == "pinned"

        comparison = _comparison(client, headers, imported)
        assert comparison["status"] == "awaiting_evidence"
        assert comparison["baseline_engine"]["executable_sha256"] == installed["executable_sha256"]
        assert comparison["candidate_engine"]["executable_sha256"] == CANDIDATE_SHA
        assert comparison["comparison_id"].startswith("cmp_")

        replayed_comparison = _comparison(client, headers, imported)
        assert replayed_comparison["comparison_id"] == comparison["comparison_id"]

        evaluated = client.post(
            f"/api/v1/comparisons/{comparison['comparison_id']}/evidence",
            headers=headers,
            json=_evidence(comparison),
        )
        assert evaluated.status_code == 200, evaluated.text
        body = evaluated.json()
        assert body["status"] == "regressed"
        assert body["result"]["upgrade_approved"] is False
        assert body["result"]["recommendation"] == "keep_current"
        assert body["result"]["contexts"][0]["status"] == "regressed"
        assert body["result"]["contexts"][0]["interval"]["upper"] < 1.0

        replay_evidence = client.post(
            f"/api/v1/comparisons/{comparison['comparison_id']}/evidence",
            headers=headers,
            json=_evidence(comparison),
        )
        assert replay_evidence.status_code == 200
        assert replay_evidence.json()["evidence_digest"] == body["evidence_digest"]

        conflicting = client.post(
            f"/api/v1/comparisons/{comparison['comparison_id']}/evidence",
            headers=headers,
            json=_evidence(comparison, candidate_throughput=(130.0, 65.0)),
        )
        assert conflicting.status_code == 409

        after = _snapshot(client, headers)
        assert after["revision"] == before["revision"]
        assert after["engines"][0]["engine"] == installed
        assert after["models"] == before["models"]

        second = _check(
            client,
            headers,
            _release(
                before,
                version="0.7.2-test",
                build="703-test",
                artifact_sha256=SECOND_CANDIDATE_SHA,
                commit="candidate-second",
            ),
        )
        second_comparison = _comparison(client, headers, second)
        incompatible = client.post(
            f"/api/v1/comparisons/{second_comparison['comparison_id']}/evidence",
            headers=headers,
            json=_evidence(second_comparison, simulated=True),
        )
        assert incompatible.status_code == 200
        assert incompatible.json()["status"] == "incompatible"
        assert incompatible.json()["result"]["upgrade_approved"] is False
        assert "SIMULATED_EVIDENCE" in incompatible.json()["result"]["reasons"]

        missing_hash = _check(
            client,
            headers,
            _release(
                before,
                version="0.7.3-test",
                build="704-test",
                artifact_sha256=None,
                commit="candidate-unhashed",
            ),
        )
        blocked = client.post(
            "/api/v1/comparisons",
            headers=headers,
            json={
                "notice_id": missing_hash["notice"]["notice_id"],
                "assessment_id": missing_hash["assessment"]["assessment_id"],
                "contexts": [4096],
            },
        )
        assert blocked.status_code == 409
        assert "SHA-256" in blocked.json()["error"]["message"]

        incomplete_identity = _check(
            client,
            headers,
            _release(
                before,
                version="0.7.4-test",
                build="705-test",
                artifact_sha256="e" * 64,
                commit="candidate-incomplete-model",
            ),
        )
        with controller.session_factory() as session:
            assessment_row = session.get(
                ReleaseAssessmentRow,
                incomplete_identity["assessment"]["assessment_id"],
            )
            assert assessment_row is not None
            payload = dict(assessment_row.payload_json)
            payload["model_identity_complete"] = False
            assessment_row.payload_json = payload
            session.commit()
        incomplete_blocked = client.post(
            "/api/v1/comparisons",
            headers=headers,
            json={
                "notice_id": incomplete_identity["notice"]["notice_id"],
                "assessment_id": incomplete_identity["assessment"]["assessment_id"],
                "contexts": [4096],
            },
        )
        assert incomplete_blocked.status_code == 409
        assert "complete model identity" in incomplete_blocked.json()["error"]["message"]
