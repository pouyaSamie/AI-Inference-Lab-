"""Supervised Optuna engine behavior against a separate SQLite database."""

from __future__ import annotations

from pathlib import Path

from lab_optimizer.engine import OptunaEngine

from lab_core import (
    AskPayload,
    CreateStudyPayload,
    DimensionKind,
    EngineId,
    FeasibilityOutcome,
    Objective,
    ParameterDimension,
    ReconcilePayload,
    SearchSpaceSpec,
    TellPayload,
    TrialTellState,
)


def _space() -> SearchSpaceSpec:
    return SearchSpaceSpec(
        engine_id=EngineId.LLAMACPP,
        dimensions=(
            ParameterDimension(name="threads", kind=DimensionKind.INT, minimum=1, maximum=4, step=1),
            ParameterDimension(name="flash_attn", kind=DimensionKind.CATEGORICAL, choices=("on", "off")),
        ),
        fixed_parameters={"gpu_layers": -1},
    )


def test_create_ask_tell_replay_and_reconcile(tmp_path: Path) -> None:
    engine = OptunaEngine(f"sqlite:///{tmp_path / 'optimizer.sqlite3'}")
    create = CreateStudyPayload(
        study_id="study-one",
        study_name="study-one",
        experiment_id="exp-one",
        max_trials=2,
        search_space=_space(),
        objective=Objective.BALANCED,
    )
    created = engine.create_study(create)
    assert created.created is True
    assert engine.create_study(create).created is False

    ask = engine.ask(
        AskPayload(
            study_id="study-one",
            study_name="study-one",
            context_tokens=4096,
            workload_digest="0" * 64,
        )
    )
    assert ask.trial_number == 0
    assert set(ask.parameters) == {"gpu_layers", "threads", "flash_attn"}

    tell = TellPayload(
        study_id="study-one",
        study_name="study-one",
        candidate_id="candidate-one",
        trial_number=ask.trial_number,
        state=TrialTellState.COMPLETE,
        value=1.25,
        feasibility=FeasibilityOutcome.FEASIBLE,
    )
    first = engine.tell(tell)
    assert first.finalized is True
    assert first.already_finalized is False
    replay = engine.tell(tell)
    assert replay.already_finalized is True
    assert replay.value == first.value

    reconcile = engine.reconcile(ReconcilePayload(study_id="study-one", study_name="study-one"))
    assert reconcile.total_trials == 1
    assert reconcile.completed_trials == 1
    assert reconcile.pending_trials == ()
    assert engine.health()["studies"] == 1
