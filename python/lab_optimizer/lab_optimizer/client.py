"""Authenticated HTTP client used by the supervised optimizer process."""

from __future__ import annotations

import logging
import time
from typing import Any, cast

import httpx

from lab_core import (
    OptimizerCompletion,
    OptimizerHeartbeat,
    OptimizerPollResponse,
)

logger = logging.getLogger(__name__)


class ControllerClientError(RuntimeError):
    pass


class ControllerClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 4,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        self.max_retries = max_retries

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ControllerClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        delay = 0.25
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.request(method, url, **kwargs)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(delay)
                    delay = min(delay * 2, 5.0)
                    continue
                response.raise_for_status()
                return response
            except (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.RemoteProtocolError,
            ) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(delay)
                delay = min(delay * 2, 5.0)
            except httpx.HTTPStatusError as exc:
                raise ControllerClientError(
                    f"controller returned {exc.response.status_code}: {exc.response.text[:500]}"
                ) from exc
        raise ControllerClientError(f"controller request failed: {last_error}") from last_error

    def heartbeat(self, heartbeat: OptimizerHeartbeat) -> None:
        self._request("POST", "/api/v1/internal/optimizer/heartbeat", json=heartbeat.model_dump(mode="json"))

    def poll(self, max_requests: int, optimizer_id: str) -> OptimizerPollResponse:
        response = self._request(
            "POST",
            "/api/v1/internal/optimizer/requests/poll",
            json={"max_requests": max_requests, "optimizer_id": optimizer_id},
        )
        return OptimizerPollResponse.model_validate(response.json())

    def complete(self, request_id: str, completion: OptimizerCompletion) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"/api/v1/internal/optimizer/requests/{request_id}/complete",
            json=completion.model_dump(mode="json"),
        )
        return cast(dict[str, Any], response.json())

    def health(self) -> dict[str, Any]:
        response = self._request("GET", "/health")
        return cast(dict[str, Any], response.json())
