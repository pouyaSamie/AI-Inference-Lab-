"""Server-Sent Events with replay, duplicate suppression and gap recovery."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from lab_core import EventType, ExperimentSnapshot

from ..config import Settings
from ..events import (
    event_to_model,
    events_after,
    latest_sequence,
    recent_events,
    replay_floor,
    status_view,
)
from ..orm import ExperimentRow


def _sse(*, event: str, data: dict[str, Any], event_id: int | None = None) -> str:
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def _snapshot_payload(session: Session, experiment: ExperimentRow) -> dict[str, Any]:
    status = status_view(session, experiment)
    snapshot = ExperimentSnapshot(
        snapshot_sequence=status.last_event_id,
        status=status,
        recent_events=tuple(event_to_model(row) for row in recent_events(session, experiment.experiment_id)),
    )
    return {
        "type": EventType.SNAPSHOT.value,
        "sequence": status.last_event_id,
        "snapshot": snapshot.model_dump(mode="json"),
    }


async def event_stream(
    request: Request,
    settings: Settings,
    session_factory: sessionmaker[Session],
    experiment_id: str,
    *,
    last_event_id: int = 0,
) -> AsyncIterator[str]:
    last_sent = max(last_event_id, 0)
    initialized = False
    keepalive_elapsed = 0.0
    while True:
        if await request.is_disconnected():
            return
        session = session_factory()
        try:
            experiment = session.get(ExperimentRow, experiment_id)
            if experiment is None:
                yield _sse(
                    event="error",
                    data={"code": "NOT_FOUND", "message": "experiment not found"},
                )
                return
            floor = replay_floor(session, experiment_id)
            if last_sent and last_sent < floor:
                latest = latest_sequence(session, experiment_id)
                yield _sse(
                    event=EventType.EVENT_GAP.value,
                    data={
                        "type": EventType.EVENT_GAP.value,
                        "requested_last_event_id": last_sent,
                        "replay_floor": floor,
                        "latest_event_id": latest,
                    },
                    event_id=latest,
                )
                yield _sse(
                    event=EventType.SNAPSHOT.value,
                    data=_snapshot_payload(session, experiment),
                    event_id=latest,
                )
                last_sent = latest
                initialized = True
                keepalive_elapsed = 0.0
            elif not initialized and last_sent == 0:
                latest = latest_sequence(session, experiment_id)
                yield _sse(
                    event=EventType.SNAPSHOT.value,
                    data=_snapshot_payload(session, experiment),
                    event_id=latest,
                )
                last_sent = latest
                initialized = True
                keepalive_elapsed = 0.0
            else:
                initialized = True

            rows = events_after(
                session,
                experiment_id,
                after_sequence=last_sent,
                limit=settings.sse_batch_size,
            )
            if rows:
                for row in rows:
                    if row.sequence <= last_sent:
                        continue
                    last_sent = row.sequence
                    yield _sse(
                        event=row.type,
                        data=event_to_model(row).model_dump(mode="json"),
                        event_id=row.sequence,
                    )
                keepalive_elapsed = 0.0
            else:
                keepalive_elapsed += settings.sse_poll_interval_seconds
                if keepalive_elapsed >= settings.sse_keepalive_seconds:
                    yield ": keepalive\n\n"
                    keepalive_elapsed = 0.0
        finally:
            session.close()

        await asyncio.sleep(settings.sse_poll_interval_seconds)
