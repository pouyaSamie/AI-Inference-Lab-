"""Model artifact identity and scoped inventory snapshots."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from .base import AwareTimestamp, FrozenModel, Identifier, JsonScalar, NonEmptyStr, NonNegativeInt, PositiveInt, Sha256
from .enums import EngineId
from .ids import sha256_hex
from .version import SCHEMA_VERSION


class ModelFile(FrozenModel):
    path: NonEmptyStr
    sha256: Sha256 | None = None
    size_bytes: NonNegativeInt = 0
    verified: bool = False
    shard_index: PositiveInt | None = None
    shard_count: PositiveInt | None = None


class ModelArtifact(FrozenModel):
    model_id: Identifier
    display_name: NonEmptyStr
    architecture: NonEmptyStr
    model_family: str | None = None
    quantization: str | None = None
    files: tuple[ModelFile, ...] = ()
    path_map: tuple[str, ...] = ()
    tokenizer_id: str | None = None
    tokenizer_sha256: Sha256 | None = None
    metadata_context_tokens: PositiveInt | None = None
    parameter_count: int | None = None
    size_bytes: NonNegativeInt = 0
    verified: bool = False
    compatible_engines: tuple[EngineId, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("files")
    @classmethod
    def _unique_files(cls, value: tuple[ModelFile, ...]) -> tuple[ModelFile, ...]:
        paths = [item.path for item in value]
        if len(paths) != len(set(paths)):
            raise ValueError("model files must have unique paths")
        return value

    @property
    def artifact_digest(self) -> str:
        """Strong identity covering every shard hash and file path."""
        return sha256_hex(
            {
                "model_id": self.model_id,
                "architecture": self.architecture,
                "files": [
                    {
                        "path": item.path,
                        "sha256": item.sha256,
                        "size_bytes": item.size_bytes,
                        "shard_index": item.shard_index,
                    }
                    for item in sorted(self.files, key=lambda item: item.path)
                ],
                "tokenizer_sha256": self.tokenizer_sha256,
                "metadata_context_tokens": self.metadata_context_tokens,
            }
        )

    def hashes_complete(self) -> bool:
        return bool(self.files) and all(item.sha256 and item.verified for item in self.files)


class ModelArtifactSnapshot(FrozenModel):
    snapshot_id: Identifier
    worker_id: Identifier
    roots: tuple[str, ...]
    artifacts: tuple[ModelArtifact, ...] = ()
    scanned_at: AwareTimestamp
    schema_version: NonEmptyStr = SCHEMA_VERSION
    warnings: tuple[str, ...] = ()

    def digest(self) -> str:
        return sha256_hex(
            {
                "worker_id": self.worker_id,
                "roots": list(self.roots),
                "artifacts": [artifact.artifact_digest for artifact in self.artifacts],
                "schema_version": self.schema_version,
            }
        )


class ModelMetadata(FrozenModel):
    """Engine-specific model understanding produced by a pure adapter."""

    architecture: NonEmptyStr
    model_type: str | None = None
    quantization: str | None = None
    context_train_tokens: int | None = None
    moe: bool = False
    expert_count: int | None = None
    tokenizer_id: str | None = None
    shard_count: int = 1
    attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_gguf(self) -> bool:
        return "gguf" in self.architecture.lower() or (self.model_type or "").lower() == "gguf"
