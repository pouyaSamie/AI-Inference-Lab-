"""Worker identity, hardware snapshots and capability inventory."""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from .base import AwareTimestamp, FrozenModel, Identifier, NonEmptyStr, NonNegativeInt, PositiveInt, Sha256
from .engine import EngineCapabilityManifest
from .ids import sha256_hex
from .model import ModelArtifact
from .version import SCHEMA_VERSION, WORKER_PROTOCOL_VERSION


class GPUDevice(FrozenModel):
    uuid: NonEmptyStr
    index: NonNegativeInt
    name: NonEmptyStr
    vram_total_bytes: PositiveInt
    driver_version: str | None = None
    compute_capability: str | None = None
    pci_bus_id: str | None = None
    mig_profile: str | None = None
    owned_by_lab: bool = True

    @field_validator("uuid")
    @classmethod
    def _uuid_prefix(cls, value: str) -> str:
        if not (value.startswith("GPU-") or value.startswith("MIG-") or value.startswith("sim-")):
            raise ValueError("GPU identity must be a physical UUID (GPU-/MIG-) or an explicit sim- id")
        return value


class HardwareSnapshot(FrozenModel):
    hostname: NonEmptyStr
    os: NonEmptyStr
    kernel: NonEmptyStr
    cpu_model: NonEmptyStr
    cpu_threads: PositiveInt
    ram_total_bytes: PositiveInt
    ram_available_bytes: NonNegativeInt
    gpus: tuple[GPUDevice, ...] = ()
    cuda_driver_version: str | None = None
    cuda_runtime_version: str | None = None
    collected_at: AwareTimestamp
    contamination_warnings: tuple[str, ...] = ()

    @field_validator("gpus")
    @classmethod
    def _unique_gpus(cls, value: tuple[GPUDevice, ...]) -> tuple[GPUDevice, ...]:
        uuids = [gpu.uuid for gpu in value]
        if len(uuids) != len(set(uuids)):
            raise ValueError("GPU UUIDs must be unique")
        return value


class WorkerIdentity(FrozenModel):
    worker_id: Identifier
    name: NonEmptyStr
    version: NonEmptyStr
    protocol_version: NonEmptyStr = WORKER_PROTOCOL_VERSION
    platform: NonEmptyStr
    enrolled_at: AwareTimestamp
    roles: tuple[str, ...] = ("benchmark",)


class WorkerHealth(FrozenModel):
    status: str = "online"
    last_heartbeat_at: AwareTimestamp
    active_leases: tuple[str, ...] = ()
    owned_pids: tuple[int, ...] = ()
    isolated: bool = True
    warnings: tuple[str, ...] = ()


class WorkerSnapshot(FrozenModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    snapshot_id: Identifier
    worker_id: Identifier
    revision: PositiveInt
    created_at: AwareTimestamp
    hardware: HardwareSnapshot
    engines: tuple[EngineCapabilityManifest, ...] = ()
    models: tuple[ModelArtifact, ...] = ()
    health: WorkerHealth
    discovery_digest: Sha256 | None = None
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _fill_digest(self) -> WorkerSnapshot:
        expected = self.compute_discovery_digest()
        if self.discovery_digest is not None and self.discovery_digest != expected:
            raise ValueError("discovery_digest does not match snapshot contents")
        object.__setattr__(self, "discovery_digest", expected)
        return self

    def compute_discovery_digest(self) -> str:
        return sha256_hex(
            {
                "worker_id": self.worker_id,
                "hardware": self.hardware.model_dump(mode="json", exclude={"ram_available_bytes", "collected_at"}),
                "engines": [engine.digest() for engine in self.engines],
                "models": [model.artifact_digest for model in self.models],
                "schema_version": self.schema_version,
            }
        )

    def engine(self, engine_id: str) -> EngineCapabilityManifest | None:
        return next((item for item in self.engines if item.engine.engine_id == engine_id), None)

    def model(self, model_id: str) -> ModelArtifact | None:
        return next((item for item in self.models if item.model_id == model_id), None)


class WorkerSummary(FrozenModel):
    worker_id: Identifier
    name: str
    status: str
    protocol_version: str
    last_heartbeat_at: AwareTimestamp | None
    snapshot_revision: int | None
    snapshot_created_at: AwareTimestamp | None
    gpus: tuple[GPUDevice, ...] = ()
    warnings: tuple[str, ...] = Field(default_factory=tuple)


class WorkerRegistration(FrozenModel):
    worker: WorkerIdentity
    hardware: HardwareSnapshot


class WorkerTokenRecord(FrozenModel):
    """Non-secret representation of a worker credential; only a hash is stored."""

    worker_id: Identifier
    token_prefix: str
    token_sha256: Sha256
    created_at: AwareTimestamp
    revoked: bool = False
