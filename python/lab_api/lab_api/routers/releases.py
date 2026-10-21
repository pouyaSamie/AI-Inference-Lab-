"""Operator-only release import, impact and regression comparison endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from lab_updates import ComparisonPlan

from ..config import Settings
from ..dependencies import get_session, get_settings
from ..schemas import (
    ComparisonCreateRequest,
    ComparisonEvidenceRequest,
    ComparisonListResponse,
    ReleaseCheckRequest,
    ReleaseCheckResponse,
    ReleaseDecisionRequest,
    ReleaseDetailResponse,
    ReleaseListResponse,
)
from ..security import Principal, require_operator
from ..services.releases import (
    create_comparison,
    get_comparison,
    import_release,
    list_comparisons,
    list_releases,
    release_detail,
    set_release_decision,
    submit_comparison_evidence,
)

router = APIRouter(tags=["releases"])


@router.post("/api/v1/releases/check", response_model=ReleaseCheckResponse)
def check_release(
    body: ReleaseCheckRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> ReleaseCheckResponse:
    return import_release(session, settings, body, actor=principal.subject)


@router.get("/api/v1/releases", response_model=ReleaseListResponse)
def list_all(
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ReleaseListResponse:
    return list_releases(session)


@router.get("/api/v1/releases/{notice_id}", response_model=ReleaseDetailResponse)
def get_one(
    notice_id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ReleaseDetailResponse:
    return release_detail(session, notice_id)


@router.post("/api/v1/releases/{notice_id}/decision", response_model=ReleaseDetailResponse)
def decide(
    notice_id: str,
    body: ReleaseDecisionRequest,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ReleaseDetailResponse:
    return set_release_decision(session, notice_id, body, actor=principal.subject)


@router.post("/api/v1/comparisons", response_model=ComparisonPlan, status_code=201)
def propose(
    body: ComparisonCreateRequest,
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ComparisonPlan:
    comparison, replay = create_comparison(session, body, actor=principal.subject)
    response.status_code = 200 if replay else 201
    return comparison


@router.get("/api/v1/comparisons", response_model=ComparisonListResponse)
def list_all_comparisons(
    notice_id: str | None = None,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ComparisonListResponse:
    return list_comparisons(session, notice_id)


@router.get("/api/v1/comparisons/{comparison_id}", response_model=ComparisonPlan)
def get_one_comparison(
    comparison_id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ComparisonPlan:
    return get_comparison(session, comparison_id)


@router.post("/api/v1/comparisons/{comparison_id}/evidence", response_model=ComparisonPlan)
def evaluate(
    comparison_id: str,
    body: ComparisonEvidenceRequest,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> ComparisonPlan:
    comparison, _replay = submit_comparison_evidence(session, comparison_id, body, actor=principal.subject)
    return comparison
