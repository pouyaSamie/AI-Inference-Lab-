"""Authenticated worker HTTP client with enrollment and durable retries."""

from __future__ import annotations

import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any, cast

import httpx
from lab_core.base import utcnow

from lab_core import (
    AckDisposition,
    CommandAck,
    CommandCompletion,
    WorkerHealth,
    WorkerIdentity,
    WorkerPollResponse,
    WorkerSnapshot,
)

from .config import WorkerSettings
from .inventory import build_hardware

logger = logging.getLogger(__name__)


class WorkerClientError(RuntimeError):
    pass


class WorkerClient:
    def __init__(self, settings: WorkerSettings, token: str | None = None, *, timeout: float = 30.0) -> None:
        self.settings = settings
        self.base_url = settings.controller_url.rstrip("/")
        self.token = token or settings.worker_token or self._load_state().get("token", "")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            headers={"Accept": "application/json"},
        )

    def _load_state(self) -> dict[str, Any]:
        path = self.settings.state_path
        try:
            return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}

    def save_state(self, **updates: Any) -> None:
        path: Path = self.settings.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        state = self._load_state()
        state.update(updates)
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            path.chmod(0o600)

    @property
    def headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WorkerClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        max_retries: int = 4,
        **kwargs: Any,
    ) -> httpx.Response:
        merged = {**self.headers, **(headers or {})}
        delay = 0.2
        last: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = self._client.request(method, path, headers=merged, **kwargs)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(delay)
                    delay = min(delay * 2, 5.0)
                    continue
                if response.status_code >= 400:
                    raise WorkerClientError(
                        f"{method} {path} -> {response.status_code}: {response.text[:800]}"
                    )
                return response
            except (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.RemoteProtocolError,
            ) as exc:
                last = exc
                if attempt >= max_retries:
                    break
                time.sleep(delay)
                delay = min(delay * 2, 5.0)
        raise WorkerClientError(f"{method} {path} failed: {last}") from last

    # ------------------------------------------------------------ enrollment
    def register(self) -> dict[str, Any]:
        identity = WorkerIdentity(
            worker_id=self.settings.worker_id,
            name=self.settings.worker_name,
            version=self.settings.worker_version,
            protocol_version=self.settings.protocol_version,
            platform="linux",
            enrolled_at=utcnow(),
            roles=("benchmark", "simulated"),
        )
        body = {
            "worker": identity.model_dump(mode="json"),
            "hardware": build_hardware(self.settings).model_dump(mode="json"),
        }
        response = self._request(
            "POST",
            "/api/v1/workers/register",
            headers={"X-Enrollment-Token": self.settings.enrollment_token},
            json=body,
            max_retries=1,
        )
        parsed = response.json()
        self.token = parsed["token"]
        self.save_state(token=self.token, worker_id=self.settings.worker_id)
        return cast(dict[str, Any], parsed)

    def upload_snapshot(self, snapshot: WorkerSnapshot) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"/api/v1/workers/{self.settings.worker_id}/snapshot",
            json={"snapshot": snapshot.model_dump(mode="json")},
        )
        return cast(dict[str, Any], response.json())

    def heartbeat(self, snapshot_revision: int) -> dict[str, Any]:
        body = {
            "health": WorkerHealth(
                status="online",
                last_heartbeat_at=utcnow(),
                active_leases=(),
                owned_pids=(),
                isolated=True,
                warnings=("PHASE_1_SIMULATED_EXECUTION",),
            ).model_dump(mode="json"),
            "snapshot_revision": snapshot_revision,
        }
        response = self._request(
            "POST",
            f"/api/v1/workers/{self.settings.worker_id}/heartbeat",
            json=body,
        )
        return cast(dict[str, Any], response.json())

    def poll(self) -> WorkerPollResponse:
        response = self._request(
            "POST",
            f"/api/v1/workers/{self.settings.worker_id}/commands/poll",
            json={"max_commands": self.settings.max_commands},
        )
        return WorkerPollResponse.model_validate(response.json())

    def ack(self, *, command_id: str, lease_token: str, lease_generation: int) -> None:
        body = CommandAck(
            lease_token=lease_token,
            disposition=AckDisposition.ACCEPTED,
            lease_generation=lease_generation,
            message="simulated worker accepted command",
        )
        self._request(
            "POST",
            f"/api/v1/workers/{self.settings.worker_id}/commands/{command_id}/ack",
            json=body.model_dump(mode="json"),
        )

    def complete(self, *, command_id: str, completion: CommandCompletion) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"/api/v1/workers/{self.settings.worker_id}/commands/{command_id}/complete",
            json=completion.model_dump(mode="json"),
        )
        return cast(dict[str, Any], response.json())
