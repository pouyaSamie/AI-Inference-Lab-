"""I/O-free adapter inputs and outputs.

Adapters receive captured facts (already-read output, registered binaries,
artifact snapshots) and return typed plans/observations. They never perform
filesystem or process I/O themselves.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .base import AwareTimestamp, FrozenModel, Identifier, NonEmptyStr, NonNegativeInt, Sha256, utcnow
from .enums import Backend, EngineId
from .ids import sha256_text
from .version import ADAPTER_SDK_VERSION


class BinaryKind(StrEnum):
    PROBE = "probe"
    MICROBENCH = "microbench"
    SERVER = "server"
    CLI = "cli"
    SERVER_SCRIPT = "server_script"


class RegisteredBinary(FrozenModel):
    executable_id: Identifier
    engine_id: EngineId
    kind: BinaryKind
    path: NonEmptyStr
    sha256: Sha256
    version: str | None = None
    build: str | None = None
    backend: Backend = Backend.UNKNOWN
    trusted: bool = True
    registered_at: AwareTimestamp = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _trusted_only(self) -> RegisteredBinary:
        if not self.trusted:
            raise ValueError("adapters only receive trusted registered binaries")
        return self


class ProcessOutput(FrozenModel):
    command_id: Identifier
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: NonNegativeInt = 0
    timed_out: bool = False
    truncated: bool = False

    @property
    def combined(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()


class RawEvidence(FrozenModel):
    evidence_id: Identifier
    path: NonEmptyStr
    content_type: NonEmptyStr
    text: str
    sha256: Sha256 | None = None

    def computed_sha256(self) -> str:
        return sha256_text(self.text)


class AdapterDescriptor(FrozenModel):
    adapter_id: EngineId
    adapter_schema: NonEmptyStr = ADAPTER_SDK_VERSION
    supported_models: tuple[str, ...] = ()
    requires_native_binary: bool = True
    notes: tuple[str, ...] = ()
