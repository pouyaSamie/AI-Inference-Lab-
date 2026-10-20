"""Optuna engine owned exclusively by the supervised optimizer process."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import optuna
from lab_core.errors import LabError
from optuna.samplers import TPESampler
from sqlalchemy.engine import make_url

from lab_core import (
    AskPayload,
    AskResult,
    CreateStudyPayload,
    DimensionKind,
    OptimizerRequestKind,
    PingPayload,
    PingResult,
    ReconcilePayload,
    ReconcileResult,
    SearchSpaceSpec,
    StudyCreatedResult,
    TellPayload,
    TellResult,
    TrialTellState,
)

logger = logging.getLogger(__name__)

optuna.logging.set_verbosity(optuna.logging.WARNING)


class OptimizerEngineError(LabError):
    code = "OPTIMIZER_ENGINE_ERROR"
    http_status = 500
    retryable = True


def _json_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise OptimizerEngineError("optimizer produced a non-finite parameter")
        return float(value)
    if isinstance(value, str) or value is None:
        return value
    if hasattr(value, "item"):
        return _json_scalar(value.item())
    raise OptimizerEngineError(f"optimizer parameter is not a JSON scalar: {type(value)!r}")


def _trial_state_name(trial: Any) -> str:
    return str(trial.state.name).lower()


class OptunaEngine:
    def __init__(self, db_url: str) -> None:
        parsed = make_url(db_url)
        if parsed.get_backend_name() != "sqlite":
            raise OptimizerEngineError("Phase 1 optimizer storage must be SQLite")
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.db_url = db_url
        self._storage = optuna.storages.RDBStorage(
            url=db_url,
            engine_kwargs={
                "connect_args": {"timeout": 30, "check_same_thread": False},
                "pool_pre_ping": True,
            },
        )

    def create_study(self, payload: CreateStudyPayload) -> StudyCreatedResult:
        existing_names = set(optuna.study.get_all_study_names(self._storage))
        created = payload.study_name not in existing_names
        study = optuna.create_study(
            study_name=payload.study_name,
            storage=self._storage,
            direction=payload.direction,
            sampler=TPESampler(seed=payload.seed),
            load_if_exists=True,
        )
        stored_space = study.user_attrs.get("search_space")
        if stored_space is not None:
            stored = SearchSpaceSpec.model_validate(stored_space)
            if stored.engine_id is not payload.search_space.engine_id:
                raise OptimizerEngineError("study exists with a different engine search space")
        study.set_user_attr("search_space", payload.search_space.model_dump(mode="json"))
        study.set_user_attr("experiment_id", payload.experiment_id)
        study.set_user_attr("study_id", payload.study_id)
        study.set_user_attr("max_trials", payload.max_trials)
        if created:
            logger.info("created Optuna study %s", payload.study_name)
        return StudyCreatedResult(
            study_name=payload.study_name,
            created=created,
            trial_count=len(study.get_trials(deepcopy=False)),
        )

    def _load(self, study_name: str) -> optuna.Study:
        try:
            return optuna.load_study(study_name=study_name, storage=self._storage)
        except KeyError as exc:
            raise OptimizerEngineError(f"Optuna study {study_name!r} does not exist") from exc

    def _suggest(
        self,
        trial: optuna.Trial,
        search_space: SearchSpaceSpec,
    ) -> dict[str, Any]:
        parameters: dict[str, Any] = {}
        for name, value in search_space.fixed_parameters.items():
            parameters[name] = _json_scalar(value)
        for dimension in search_space.dimensions:
            if not search_space.is_active(dimension, parameters):
                continue
            if dimension.kind is DimensionKind.CATEGORICAL or dimension.kind is DimensionKind.BOOL:
                parameters[dimension.name] = _json_scalar(
                    trial.suggest_categorical(dimension.name, list(dimension.choices))
                )
            elif dimension.kind is DimensionKind.INT:
                assert dimension.minimum is not None and dimension.maximum is not None
                parameters[dimension.name] = int(
                    trial.suggest_int(
                        dimension.name,
                        int(dimension.minimum),
                        int(dimension.maximum),
                        step=max(1, int(dimension.step or 1)),
                        log=dimension.log,
                    )
                )
            elif dimension.kind is DimensionKind.FLOAT:
                assert dimension.minimum is not None and dimension.maximum is not None
                parameters[dimension.name] = float(
                    trial.suggest_float(
                        dimension.name,
                        float(dimension.minimum),
                        float(dimension.maximum),
                        step=float(dimension.step) if dimension.step else None,
                        log=dimension.log,
                    )
                )
        return parameters

    def ask(self, payload: AskPayload) -> AskResult:
        study = self._load(payload.study_name)
        search_space = SearchSpaceSpec.model_validate(study.user_attrs.get("search_space"))
        trial = study.ask()
        try:
            parameters = self._suggest(trial, search_space)
        except Exception as exc:
            study.tell(trial.number, state=optuna.trial.TrialState.FAIL)
            raise OptimizerEngineError(f"failed to suggest parameters: {exc}") from exc
        return AskResult(
            study_name=payload.study_name,
            trial_number=trial.number,
            parameters=parameters,
        )

    def tell(self, payload: TellPayload) -> TellResult:
        study = self._load(payload.study_name)
        trial = next(
            (item for item in study.get_trials(deepcopy=False) if item.number == payload.trial_number), None
        )
        if trial is None:
            raise OptimizerEngineError(
                f"Optuna trial {payload.trial_number} does not exist in study {payload.study_name}"
            )
        if trial.state.is_finished():
            return TellResult(
                study_name=payload.study_name,
                trial_number=payload.trial_number,
                trial_state=_trial_state_name(trial),
                finalized=True,
                already_finalized=True,
                value=trial.value,
            )
        if payload.state is TrialTellState.COMPLETE:
            if payload.value is None:
                raise OptimizerEngineError("completed tell requires a value")
            study.tell(payload.trial_number, values=float(payload.value))
        elif payload.state is TrialTellState.FAIL:
            study.tell(trial.number, state=optuna.trial.TrialState.FAIL)
        elif payload.state is TrialTellState.PRUNED:
            study.tell(payload.trial_number, state=optuna.trial.TrialState.PRUNED)
        else:  # pragma: no cover - exhaustive
            raise OptimizerEngineError(f"unsupported tell state: {payload.state!r}")
        refreshed = next(
            item for item in study.get_trials(deepcopy=False) if item.number == payload.trial_number
        )
        return TellResult(
            study_name=payload.study_name,
            trial_number=payload.trial_number,
            trial_state=_trial_state_name(refreshed),
            finalized=True,
            already_finalized=False,
            value=refreshed.value,
        )

    def reconcile(self, payload: ReconcilePayload) -> ReconcileResult:
        study = self._load(payload.study_name)
        trials = study.get_trials(deepcopy=False)
        completed = sum(1 for trial in trials if trial.state is optuna.trial.TrialState.COMPLETE)
        failed = sum(
            1
            for trial in trials
            if trial.state in (optuna.trial.TrialState.FAIL, optuna.trial.TrialState.PRUNED)
        )
        pending = tuple(
            {"trial_number": trial.number, "state": _trial_state_name(trial)}
            for trial in trials
            if not trial.state.is_finished()
        )
        return ReconcileResult(
            study_name=payload.study_name,
            total_trials=len(trials),
            completed_trials=completed,
            failed_trials=failed,
            pending_trials=pending,
        )

    def open_study_count(self) -> int:
        try:
            return len(optuna.study.get_all_study_names(self._storage))
        except Exception:
            return 0

    def health(self) -> dict[str, Any]:
        names = optuna.study.get_all_study_names(self._storage)
        return {"storage": "ok", "studies": len(names), "optuna_version": str(optuna.__version__)}

    def dispatch(self, kind: OptimizerRequestKind, payload: Any) -> Any:
        if kind is OptimizerRequestKind.CREATE_STUDY:
            return self.create_study(payload)
        if kind is OptimizerRequestKind.ASK:
            return self.ask(payload)
        if kind is OptimizerRequestKind.TELL:
            return self.tell(payload)
        if kind is OptimizerRequestKind.RECONCILE:
            return self.reconcile(payload)
        if kind is OptimizerRequestKind.PING:
            assert isinstance(payload, PingPayload)
            return PingResult(
                optimizer_version=self.health()["optuna_version"],
                note=payload.note,
            )
        raise OptimizerEngineError(f"unsupported optimizer request kind: {kind!r}")
