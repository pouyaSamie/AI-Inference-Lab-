"""Recipe inspection and worker-mediated verification/promotion commands."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header
from lab_core.errors import ConflictError, NotFoundError
from sqlalchemy.orm import Session

from lab_core import CommandType, PromotePayload, VerifyRecipePayload

from ..config import Settings
from ..dependencies import get_session, get_settings
from ..idempotency import require_key
from ..orm import RecipeRow
from ..schemas import PromotionRequest, RecipeCreateRequest, RecipeListResponse, RecipeView
from ..security import Principal, require_operator
from ..services.commands import enqueue_command
from ..services.recipes import create_recipe, get_recipe, list_recipes

router = APIRouter(tags=["recipes"])


@router.post("/api/v1/recipes", response_model=RecipeView, status_code=201)
def create(
    body: RecipeCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> RecipeView:
    require_key(idempotency_key)
    return create_recipe(session, settings, body.experiment_id, body.candidate_id)


@router.get("/api/v1/recipes", response_model=RecipeListResponse)
def list_all(
    experiment_id: str | None = None,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> RecipeListResponse:
    recipes = list_recipes(session, experiment_id)
    return RecipeListResponse(recipes=recipes, total=len(recipes))


@router.get("/api/v1/recipes/{recipe_id}", response_model=RecipeView)
def get_one(
    recipe_id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_operator),
) -> RecipeView:
    return get_recipe(session, recipe_id)


def _recipe_worker_and_identities(session: Session, recipe_id: str) -> tuple[str, str, str]:
    row = session.get(RecipeRow, recipe_id)
    if row is None:
        raise NotFoundError("recipe not found")
    manifest = row.manifest_json or {}
    worker_id = (manifest.get("hardware") or {}).get("worker_id")
    engine_sha = (manifest.get("engine") or {}).get("sha256")
    model_digest = (manifest.get("model") or {}).get("artifact_digest")
    if not worker_id:
        raise ConflictError("recipe does not identify the worker that produced it")
    if not engine_sha or not model_digest:
        raise ConflictError("recipe is missing engine or model validation identity")
    return worker_id, engine_sha, model_digest


@router.post("/api/v1/recipes/{recipe_id}/verify")
def verify(
    recipe_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> dict[str, Any]:
    worker_id, engine_sha, model_digest = _recipe_worker_and_identities(session, recipe_id)
    recipe = get_recipe(session, recipe_id)
    command = enqueue_command(
        session,
        settings,
        worker_id=worker_id,
        command_type=CommandType.VERIFY_RECIPE,
        payload=VerifyRecipePayload(
            recipe_id=recipe_id,
            recipe_digest=recipe.recipe_digest,
            expected_engine_sha256=engine_sha,
            expected_model_digest=model_digest,
        ),
        idempotency_key=f"verify:{recipe_id}",
    )
    session.commit()
    return {"command_id": command.command_id, "status": command.status}


@router.post("/api/v1/recipes/{recipe_id}/promote")
def promote(
    recipe_id: str,
    body: PromotionRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_operator),
) -> dict[str, Any]:
    worker_id, _, _ = _recipe_worker_and_identities(session, recipe_id)
    recipe = get_recipe(session, recipe_id)
    command = enqueue_command(
        session,
        settings,
        worker_id=worker_id,
        command_type=CommandType.PROMOTE,
        payload=PromotePayload(
            recipe_id=recipe_id,
            recipe_digest=recipe.recipe_digest,
            target_slot=body.target_slot,
            dry_run=body.dry_run,
        ),
        idempotency_key=f"promote:{recipe_id}:{body.target_slot}:{body.dry_run}",
    )
    session.commit()
    return {"command_id": command.command_id, "status": command.status}
