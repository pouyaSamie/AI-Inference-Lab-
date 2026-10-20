"""Explicit exception taxonomy shared by the controller and services.

Every error crossing the API boundary is rendered as a typed envelope with a
stable machine-readable ``code``. Errors never turn into synthetic metrics.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LabError(Exception):
    code: str = "LAB_ERROR"
    http_status: int = 400
    retryable: bool = False
    recovery_hint: str = "Inspect the request and retry after correcting the input."

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
        recovery_hint: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if retryable is not None:
            self.retryable = retryable
        if recovery_hint is not None:
            self.recovery_hint = recovery_hint
        if http_status is not None:
            self.http_status = http_status


class ValidationFailure(LabError):
    code = "VALIDATION_ERROR"
    http_status = 422


class AuthenticationError(LabError):
    code = "UNAUTHORIZED"
    http_status = 401
    recovery_hint = "Provide a valid bearer token with the required role."


class AuthorizationError(LabError):
    code = "FORBIDDEN"
    http_status = 403
    recovery_hint = "Use an operator/admin credential or request access from the lab administrator."


class NotFoundError(LabError):
    code = "NOT_FOUND"
    http_status = 404


class ConflictError(LabError):
    code = "CONFLICT"
    http_status = 409


class IdempotencyConflictError(LabError):
    code = "IDEMPOTENCY_CONFLICT"
    http_status = 409
    recovery_hint = "Reuse the original idempotency key only with an identical request body."


class StalePlanError(LabError):
    code = "PLAN_STALE"
    http_status = 409
    recovery_hint = "Request a new plan; the worker inventory changed since the plan digest was issued."


class InvalidTransitionError(LabError):
    code = "INVALID_TRANSITION"
    http_status = 409
    recovery_hint = "Inspect the current experiment state before retrying the transition."


class WorkerOfflineError(LabError):
    code = "WORKER_OFFLINE"
    http_status = 409
    retryable = True
    recovery_hint = "Wait for the worker heartbeat to recover, then retry or request a preflight."


class PreflightRequiredError(LabError):
    code = "PREFLIGHT_REQUIRED"
    http_status = 409
    recovery_hint = "Complete the queued scan/preflight command, then request the plan again."


class LeaseConflictError(LabError):
    code = "LEASE_CONFLICT"
    http_status = 409
    recovery_hint = "Wait for lease expiry or reconcile the worker's owned processes."


class OptimizerUnavailableError(LabError):
    code = "OPTIMIZER_UNAVAILABLE"
    http_status = 503
    retryable = True
    recovery_hint = "Start the supervised optimizer process and retry once its heartbeat is fresh."


class UnsupportedCapabilityError(LabError):
    code = "UNSUPPORTED_CAPABILITY"
    http_status = 422


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    retryable: bool = False
    recovery_hint: str | None = None
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    error: ErrorBody
