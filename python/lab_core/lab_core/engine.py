"""Engine identity, capability descriptors and compatibility contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .base import AwareTimestamp, FrozenModel, JsonScalar, NonEmptyStr, Sha256
from .enums import Backend, EngineId, ImpactClass
from .version import SCHEMA_VERSION


class CapabilityKind(StrEnum):
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    ENUM = "enum"
    STRING = "string"


class CapabilityProvenance(StrEnum):
    OBSERVED_CLI = "observed_cli"
    OBSERVED_SERVER_API = "observed_server_api"
    APPROVED_RULE = "approved_rule"
    INSTALLED_MANIFEST = "installed_manifest"
    UNVERIFIED = "unverified"


class SupportLevel(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    CONDITIONAL = "conditional"


class EngineIdentity(FrozenModel):
    engine_id: EngineId
    adapter_schema: NonEmptyStr = SCHEMA_VERSION
    version: NonEmptyStr
    build: NonEmptyStr
    backend: Backend = Backend.UNKNOWN
    executable_id: NonEmptyStr
    executable_sha256: Sha256
    executable_path: NonEmptyStr | None = None
    source_commit: str | None = None
    source_digest: Sha256 | None = None


class CapabilityDescriptor(FrozenModel):
    """One observed, typed engine parameter.

    Flags absent from the installed binary must not be represented as
    supported. ``provenance`` records how support was established.
    """

    key: NonEmptyStr
    kind: CapabilityKind
    support: SupportLevel = SupportLevel.SUPPORTED
    legal_values: tuple[JsonScalar, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    default: JsonScalar = None
    constraints: tuple[str, ...] = ()
    incompatibilities: tuple[str, ...] = ()
    impact_class: ImpactClass = ImpactClass.P2
    restart_required: bool = False
    quality_risk: bool = False
    provenance: CapabilityProvenance = CapabilityProvenance.OBSERVED_CLI

    @model_validator(mode="after")
    def _validate_shape(self) -> CapabilityDescriptor:
        if self.kind is CapabilityKind.ENUM and not self.legal_values:
            raise ValueError(f"enum capability {self.key!r} requires legal_values")
        if self.kind is CapabilityKind.INT and self.minimum is None and self.maximum is None:
            # Integer capabilities may be open-ended, but both bounds are
            # strongly preferred; do not guess a range.
            return self
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError(f"capability {self.key!r} has minimum > maximum")
        return self


class EngineCapabilityManifest(FrozenModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    engine: EngineIdentity
    backend: Backend
    probed_at: AwareTimestamp
    descriptors: tuple[CapabilityDescriptor, ...] = ()
    help_sha256: Sha256 | None = None
    version_output_sha256: Sha256 | None = None
    notes: tuple[str, ...] = ()

    @property
    def flags(self) -> frozenset[str]:
        return frozenset(descriptor.key for descriptor in self.descriptors)

    def descriptor(self, key: str) -> CapabilityDescriptor | None:
        return next((item for item in self.descriptors if item.key == key), None)

    def require_supported(self, keys: tuple[str, ...]) -> list[str]:
        return [key for key in keys if key not in self.flags]


class CompatibilityResult(FrozenModel):
    compatible: bool
    engine_id: EngineId
    model_id: NonEmptyStr
    checked_at: AwareTimestamp
    reasons: tuple[str, ...] = ()
    unsupported_parameters: tuple[str, ...] = ()
    required_model_files: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    support: Literal["supported", "unsupported", "unknown", "conditional"] = "unknown"

    @model_validator(mode="after")
    def _consistent(self) -> CompatibilityResult:
        if self.compatible and self.support == "unsupported":
            raise ValueError("compatible result cannot have support=unsupported")
        return self
