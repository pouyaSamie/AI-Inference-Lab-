"""Read-only release intelligence, decisions and paired engine comparisons."""

from __future__ import annotations

from lab_core.errors import ConflictError, NotFoundError
from sqlalchemy import select
from sqlalchemy.orm import Session

from lab_core import (
    EngineIdentity,
    ModelArtifact,
    WorkerSnapshot,
)
from lab_updates import (
    ComparisonEvidence,
    ComparisonPlan,
    ImpactAssessment,
    ReleaseDecision,
    ReleaseMetadata,
    assess_release_impact,
    completed_comparison,
    freeze_comparison,
)

from ..config import Settings
from ..orm import (
    AuditEventRow,
    EngineComparisonRow,
    ReleaseAssessmentRow,
    ReleaseNoticeRow,
    WorkerRow,
    WorkerSnapshotRow,
    as_utc,
    utcnow,
)
from ..schemas import (
    ComparisonCreateRequest,
    ComparisonEvidenceRequest,
    ComparisonListResponse,
    ReleaseCheckRequest,
    ReleaseCheckResponse,
    ReleaseDecisionRequest,
    ReleaseDetailResponse,
    ReleaseListResponse,
    ReleaseNoticeView,
)
from ..services.inventory import (
    find_engine,
    find_model,
    latest_snapshot,
    snapshot_freshness,
    snapshot_model,
)


def _notice_view(row: ReleaseNoticeRow) -> ReleaseNoticeView:
    return ReleaseNoticeView(
        notice_id=row.notice_id,
        release=ReleaseMetadata.model_validate(row.metadata_json),
        metadata_digest=row.metadata_digest,
        imported_at=as_utc(row.imported_at) or utcnow(),
        decision=ReleaseDecision(row.decision),
        decision_note=row.decision_note,
        decision_at=as_utc(row.decision_at),
    )


def _assessment_view(row: ReleaseAssessmentRow) -> ImpactAssessment:
    return ImpactAssessment.model_validate(row.payload_json)


def _comparison_view(row: EngineComparisonRow) -> ComparisonPlan:
    return ComparisonPlan.model_validate(row.payload_json)


def _get_notice(session: Session, notice_id: str) -> ReleaseNoticeRow:
    row = session.get(ReleaseNoticeRow, notice_id)
    if row is None:
        raise NotFoundError("release notice not found", details={"notice_id": notice_id})
    return row


def _get_comparison(session: Session, comparison_id: str) -> EngineComparisonRow:
    row = session.get(EngineComparisonRow, comparison_id)
    if row is None:
        raise NotFoundError("comparison not found", details={"comparison_id": comparison_id})
    return row


def _worker_snapshot(session: Session, worker_id: str) -> tuple[WorkerRow, WorkerSnapshotRow, WorkerSnapshot]:
    worker = session.get(WorkerRow, worker_id)
    if worker is None:
        raise NotFoundError("worker not found", details={"worker_id": worker_id})
    row = latest_snapshot(session, worker_id)
    if row is None:
        raise ConflictError(
            "worker has no cached inventory snapshot",
            details={"worker_id": worker_id},
            recovery_hint="Wait for the worker scan to complete before assessing a release.",
        )
    return worker, row, snapshot_model(row)


def _audit(
    session: Session,
    *,
    actor: str,
    action: str,
    target: str,
    payload: dict[str, object],
) -> None:
    session.add(
        AuditEventRow(
            actor=actor,
            action=action,
            target=target,
            payload_json=payload,
            created_at=utcnow(),
        )
    )


def import_release(
    session: Session,
    settings: Settings,
    body: ReleaseCheckRequest,
    *,
    actor: str,
) -> ReleaseCheckResponse:
    """Import offline release metadata and assess it against cached inventory.

    No upstream request is made. A repeated identical import returns the same
    durable notice and assessment rather than creating a second release.
    """

    worker, snapshot_row, snapshot = _worker_snapshot(session, body.worker_id)
    fresh, _freshness_reasons = snapshot_freshness(settings, worker, snapshot_row)
    model: ModelArtifact | None = None
    if body.model_id is not None:
        model = find_model(snapshot, body.model_id)
        if model is None:
            raise NotFoundError(
                "model is not present in the worker snapshot",
                details={"worker_id": body.worker_id, "model_id": body.model_id},
            )

    release = body.release
    current_manifest = find_engine(snapshot, release.engine_id)
    assessment = assess_release_impact(
        release,
        worker_id=body.worker_id,
        model_id=body.model_id,
        model=model,
        current_manifest=current_manifest,
        inventory_snapshot_revision=snapshot_row.revision,
        inventory_digest=snapshot_row.discovery_digest,
        inventory_fresh=fresh,
        gpu_uuids=tuple(gpu.uuid for gpu in snapshot.hardware.gpus),
    )

    notice = session.scalar(
        select(ReleaseNoticeRow).where(ReleaseNoticeRow.metadata_digest == release.digest())
    )
    imported = notice is None
    if notice is None:
        now = utcnow()
        notice = ReleaseNoticeRow(
            notice_id=release.notice_id,
            engine_id=release.engine_id.value,
            version=release.version,
            build=release.build,
            source=release.source.value,
            metadata_digest=release.digest(),
            metadata_json=release.model_dump(mode="json"),
            decision=ReleaseDecision.PENDING.value,
            imported_at=now,
            updated_at=now,
        )
        session.add(notice)
        session.flush()

    assessment_row = session.get(ReleaseAssessmentRow, assessment.assessment_id)
    if assessment_row is None:
        assessment_row = ReleaseAssessmentRow(
            assessment_id=assessment.assessment_id,
            notice_id=notice.notice_id,
            worker_id=body.worker_id,
            model_id=body.model_id or "",
            model_digest=assessment.model_digest or "",
            policy_version=assessment.policy_version,
            current_engine_sha256=(
                assessment.current_engine.executable_sha256 if assessment.current_engine is not None else ""
            ),
            inventory_snapshot_revision=assessment.inventory_snapshot_revision,
            inventory_fresh=assessment.inventory_fresh,
            applicable=assessment.applicable,
            impact=assessment.impact.value,
            requires_ab=assessment.requires_ab,
            recommended_action=assessment.recommended_action.value,
            payload_json=assessment.model_dump(mode="json"),
            created_at=utcnow(),
        )
        session.add(assessment_row)

    already_installed = "RELEASE_ALREADY_INSTALLED" in assessment.reasons
    if already_installed:
        result: str = "already_installed"
    elif imported:
        result = "imported"
    else:
        result = "reused"

    _audit(
        session,
        actor=actor,
        action="release.checked",
        target=notice.notice_id,
        payload={
            "worker_id": body.worker_id,
            "model_id": body.model_id or "",
            "result": result,
            "impact": assessment.impact.value,
            "applicable": assessment.applicable,
        },
    )
    session.commit()
    return ReleaseCheckResponse(
        result=result,
        notice=_notice_view(notice),
        assessment=assessment,
    )


def list_releases(session: Session) -> ReleaseListResponse:
    rows = session.scalars(
        select(ReleaseNoticeRow).order_by(ReleaseNoticeRow.imported_at.desc(), ReleaseNoticeRow.notice_id)
    ).all()
    notices = tuple(_notice_view(row) for row in rows)
    return ReleaseListResponse(notices=notices, total=len(notices))


def release_detail(session: Session, notice_id: str) -> ReleaseDetailResponse:
    notice = _get_notice(session, notice_id)
    assessment_rows = session.scalars(
        select(ReleaseAssessmentRow)
        .where(ReleaseAssessmentRow.notice_id == notice_id)
        .order_by(ReleaseAssessmentRow.created_at.desc(), ReleaseAssessmentRow.assessment_id)
    ).all()
    comparison_rows = session.scalars(
        select(EngineComparisonRow)
        .where(EngineComparisonRow.notice_id == notice_id)
        .order_by(EngineComparisonRow.created_at.desc(), EngineComparisonRow.comparison_id)
    ).all()
    return ReleaseDetailResponse(
        notice=_notice_view(notice),
        assessments=tuple(_assessment_view(row) for row in assessment_rows),
        comparisons=tuple(_comparison_view(row) for row in comparison_rows),
    )


def set_release_decision(
    session: Session,
    notice_id: str,
    body: ReleaseDecisionRequest,
    *,
    actor: str,
) -> ReleaseDetailResponse:
    notice = _get_notice(session, notice_id)
    notice.decision = ReleaseDecision.PINNED.value if body.action == "pin" else ReleaseDecision.DEFERRED.value
    notice.decision_note = body.note
    notice.decision_at = utcnow()
    notice.updated_at = utcnow()
    _audit(
        session,
        actor=actor,
        action="release.decision",
        target=notice_id,
        payload={"decision": notice.decision, "note": body.note or ""},
    )
    session.commit()
    return release_detail(session, notice_id)


def create_comparison(
    session: Session,
    body: ComparisonCreateRequest,
    *,
    actor: str,
) -> tuple[ComparisonPlan, bool]:
    notice = _get_notice(session, body.notice_id)
    assessment_row = session.get(ReleaseAssessmentRow, body.assessment_id)
    if assessment_row is None or assessment_row.notice_id != notice.notice_id:
        raise NotFoundError(
            "release assessment not found",
            details={"notice_id": body.notice_id, "assessment_id": body.assessment_id},
        )
    assessment = _assessment_view(assessment_row)
    if not assessment.applicable or not assessment.requires_ab:
        raise ConflictError(
            "release is not applicable or does not require an A/B comparison",
            details={
                "applicable": assessment.applicable,
                "requires_ab": assessment.requires_ab,
                "reasons": list(assessment.reasons),
            },
            recovery_hint="Review the impact assessment; only applicable P0/P1 releases can be compared.",
        )
    current = assessment.current_engine
    if current is None:
        raise ConflictError("assessment did not capture the installed baseline engine")
    if assessment.model_id is None or assessment.model_digest is None:
        raise ConflictError("assessment is missing the selected model identity")
    if not assessment.model_identity_complete:
        raise ConflictError(
            "complete model identity digest is required for a safe A/B comparison",
            details={
                "model_id": assessment.model_id,
                "model_digest": assessment.model_digest,
                "model_identity_complete": False,
            },
            recovery_hint=(
                "Re-scan and hash every model file, then import the release again so the "
                "assessment binds a complete model identity."
            ),
        )
    release = ReleaseMetadata.model_validate(notice.metadata_json)
    candidate_sha = release.candidate_executable_sha256
    if candidate_sha is None:
        raise ConflictError(
            "release artifact SHA-256 is required for a safe A/B comparison",
            details={"notice_id": notice.notice_id},
            recovery_hint="Import official release metadata that includes the candidate executable hash.",
        )
    if candidate_sha == current.executable_sha256:
        raise ConflictError("candidate executable hash equals the installed baseline")
    candidate = EngineIdentity(
        engine_id=release.engine_id,
        version=release.version,
        build=release.build,
        backend=release.backend,
        executable_id=release.executable_id or current.executable_id,
        executable_sha256=candidate_sha,
        source_commit=release.source_commit,
        source_digest=candidate_sha,
    )
    plan = freeze_comparison(
        notice_id=notice.notice_id,
        assessment_id=assessment.assessment_id,
        worker_id=assessment.worker_id,
        model_id=assessment.model_id,
        model_digest=assessment.model_digest,
        baseline_engine=current,
        candidate_engine=candidate,
        contexts=body.contexts,
        objective=body.objective,
        workload=body.workload,
        gpu_uuids=assessment.gpu_uuids,
        min_improvement_pct=body.min_improvement_pct,
        confidence_level=body.confidence_level,
    )
    existing = session.get(EngineComparisonRow, plan.comparison_id)
    if existing is not None:
        return _comparison_view(existing), True

    now = utcnow()
    row = EngineComparisonRow(
        comparison_id=plan.comparison_id,
        notice_id=notice.notice_id,
        assessment_id=assessment.assessment_id,
        worker_id=plan.worker_id,
        model_id=plan.model_id,
        model_digest=plan.model_digest,
        objective=plan.objective.value,
        status=plan.status.value,
        payload_json=plan.model_dump(mode="json"),
        created_at=now,
    )
    session.add(row)
    notice.decision = ReleaseDecision.COMPARISON_REQUESTED.value
    notice.updated_at = now
    _audit(
        session,
        actor=actor,
        action="release.comparison.proposed",
        target=plan.comparison_id,
        payload={
            "notice_id": notice.notice_id,
            "worker_id": plan.worker_id,
            "model_id": plan.model_id,
            "contexts": [int(item) for item in plan.contexts],
        },
    )
    session.commit()
    return plan, False


def list_comparisons(session: Session, notice_id: str | None = None) -> ComparisonListResponse:
    query = select(EngineComparisonRow).order_by(
        EngineComparisonRow.created_at.desc(), EngineComparisonRow.comparison_id
    )
    if notice_id is not None:
        query = query.where(EngineComparisonRow.notice_id == notice_id)
    rows = session.scalars(query).all()
    comparisons = tuple(_comparison_view(row) for row in rows)
    return ComparisonListResponse(comparisons=comparisons, total=len(comparisons))


def get_comparison(session: Session, comparison_id: str) -> ComparisonPlan:
    return _comparison_view(_get_comparison(session, comparison_id))


def submit_comparison_evidence(
    session: Session,
    comparison_id: str,
    body: ComparisonEvidenceRequest,
    *,
    actor: str,
) -> tuple[ComparisonPlan, bool]:
    row = _get_comparison(session, comparison_id)
    plan = _comparison_view(row)
    evidence = ComparisonEvidence(
        comparison_id=comparison_id,
        worker_id=body.worker_id,
        model_digest=body.model_digest,
        workload_digest=body.workload_digest,
        baseline_engine_sha256=body.baseline_engine_sha256,
        candidate_engine_sha256=body.candidate_engine_sha256,
        simulated=body.simulated,
        measurement_status=body.measurement_status,
        samples=body.samples,
        notes=body.notes,
    )
    digest = evidence.digest()
    if row.status != "awaiting_evidence":
        if row.evidence_digest == digest:
            return plan, True
        raise ConflictError(
            "comparison already has a terminal result",
            details={"comparison_id": comparison_id, "status": row.status},
            recovery_hint="Create a new comparison proposal to evaluate different evidence.",
        )

    completed = completed_comparison(plan, evidence)
    now = utcnow()
    row.payload_json = completed.model_dump(mode="json")
    row.status = completed.status.value
    row.evidence_digest = digest
    row.evaluated_at = now
    _audit(
        session,
        actor=actor,
        action="release.comparison.evaluated",
        target=comparison_id,
        payload={
            "status": completed.status.value,
            "recommendation": completed.result.recommendation.value if completed.result else "",
            "upgrade_approved": False,
        },
    )
    session.commit()
    return completed, False
