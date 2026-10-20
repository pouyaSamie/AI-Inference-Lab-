"""Typed execution plans produced by pure adapters and consumed by workers."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from .base import AwareTimestamp, FrozenModel, Identifier, NonEmptyStr, PositiveInt, Sha256, utcnow
from .enums import EngineId
from .ids import sha256_text, stable_id
from .version import SCHEMA_VERSION


class ArtifactKind(StrEnum):
    STDOUT = "stdout"
    STDERR = "stderr"
    RAW_JSON = "raw_json"
    LOG = "log"
    METRICS = "metrics"
    PROFILE = "profile"
    RECIPE = "recipe"


class ArtifactPath(FrozenModel):
    kind: ArtifactKind
    relative_path: NonEmptyStr
    required: bool = False
    content_type: str = "application/octet-stream"


class ReadinessKind(StrEnum):
    HTTP = "http"
    OUTPUT_PATTERN = "output_pattern"
    PROCESS_ALIVE = "process_alive"
    NONE = "none"


class ReadinessPredicate(FrozenModel):
    kind: ReadinessKind = ReadinessKind.NONE
    target: str | None = None
    timeout_seconds: PositiveInt = 60
    interval_ms: PositiveInt = 250
    expected_status: int = 200

    @model_validator(mode="after")
    def _target_required(self) -> ReadinessPredicate:
        if self.kind in (ReadinessKind.HTTP, ReadinessKind.OUTPUT_PATTERN) and not self.target:
            raise ValueError("readiness predicate requires a target")
        if (
            self.kind is ReadinessKind.HTTP
            and self.target
            and not self.target.startswith(("http://", "https://"))
        ):
            raise ValueError("HTTP readiness target must be an explicit loopback URL")
        return self


class SandboxPaths(FrozenModel):
    """Paths supplied by the worker, never invented by an adapter."""

    root: NonEmptyStr
    work_dir: NonEmptyStr
    log_dir: NonEmptyStr
    artifact_dir: NonEmptyStr
    temp_home: NonEmptyStr

    @model_validator(mode="after")
    def _under_root(self) -> SandboxPaths:
        for name in ("work_dir", "log_dir", "artifact_dir", "temp_home"):
            value = getattr(self, name)
            if not (value == self.root or value.startswith(self.root.rstrip("/") + "/")):
                raise ValueError(f"{name} must be inside the sandbox root")
        return self


class GeneratedFile(FrozenModel):
    relative_path: NonEmptyStr
    content: str
    sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _safe_path(self) -> GeneratedFile:
        if self.relative_path.startswith("/") or ".." in self.relative_path.split("/"):
            raise ValueError("generated files must use a safe relative path")
        expected = sha256_text(self.content)
        if self.sha256 is not None and self.sha256 != expected:
            raise ValueError("generated file digest does not match content")
        object.__setattr__(self, "sha256", expected)
        return self


class CommandSpec(FrozenModel):
    """An immutable argv array. The runner never interprets a shell string.

    ``argv`` contains arguments after the trusted executable resolved from
    ``executable_id``. The worker resolves that ID through its allowlisted
    registry and verifies ``executable_sha256`` before spawning.
    """

    executable_id: NonEmptyStr
    executable_sha256: Sha256
    argv: tuple[str, ...]
    env: dict[str, str] = Field(default_factory=dict)
    cwd: NonEmptyStr
    timeout_seconds: PositiveInt
    readiness: ReadinessPredicate = Field(default_factory=ReadinessPredicate)
    stdout_schema: NonEmptyStr | None = None
    artifacts: tuple[ArtifactPath, ...] = ()

    @field_validator("argv")
    @classmethod
    def _argv_safe(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if "\x00" in item:
                raise ValueError("argv entries must not contain NUL bytes")
        return value

    @field_validator("env")
    @classmethod
    def _env_keys(cls, value: dict[str, str]) -> dict[str, str]:
        for key in value:
            if not key.replace("_", "").isalnum() or key[0].isdigit():
                raise ValueError(f"invalid environment variable name: {key!r}")
            if key.upper() in {"LD_PRELOAD", "LD_LIBRARY_PATH"} and ".." in value[key]:
                raise ValueError("environment path must not contain '..'")
        return value


class ExecutionStage(FrozenModel):
    name: NonEmptyStr
    command: CommandSpec
    required: bool = True
    description: str | None = None


class ExecutionPlan(FrozenModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    plan_id: Identifier = ""
    engine_id: EngineId
    candidate_digest: Sha256
    sandbox: SandboxPaths
    stages: tuple[ExecutionStage, ...]
    generated_files: tuple[GeneratedFile, ...] = ()
    expected_observation_schema: NonEmptyStr
    created_at: AwareTimestamp = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _fill_plan_id(self) -> ExecutionPlan:
        expected = stable_id(
            "exec",
            self.engine_id,
            self.candidate_digest,
            [stage.command.model_dump(mode="json") for stage in self.stages],
            self.sandbox.model_dump(mode="json"),
            [item.sha256 for item in self.generated_files],
        )
        if self.plan_id and self.plan_id != expected:
            raise ValueError("plan_id does not match execution plan contents")
        object.__setattr__(self, "plan_id", expected)
        return self


class ServerExecutionPlan(FrozenModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    plan_id: Identifier = ""
    engine_id: EngineId
    candidate_digest: Sha256
    sandbox: SandboxPaths
    start: ExecutionStage
    bind_host: str = "127.0.0.1"
    port_range_start: PositiveInt
    port_range_end: PositiveInt
    health_path: NonEmptyStr = "/health"
    metrics_path: str | None = None
    readiness_timeout_seconds: PositiveInt = 120
    created_at: AwareTimestamp = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _port_range(self) -> ServerExecutionPlan:
        if self.port_range_start > self.port_range_end:
            raise ValueError("port_range_start must be <= port_range_end")
        if self.bind_host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("server plans must bind to loopback")
        expected = stable_id(
            "srvplan",
            self.engine_id,
            self.candidate_digest,
            self.start.command.model_dump(mode="json"),
            self.sandbox.model_dump(mode="json"),
            self.bind_host,
            self.port_range_start,
            self.port_range_end,
        )
        if self.plan_id and self.plan_id != expected:
            raise ValueError("plan_id does not match server plan contents")
        object.__setattr__(self, "plan_id", expected)
        return self


class RawEvidenceRef(FrozenModel):
    path: NonEmptyStr
    sha256: Sha256
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    description: str | None = None
