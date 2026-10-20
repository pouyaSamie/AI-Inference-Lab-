"""Versioned, pure inference-adapter contract.

Adapters may import only stdlib, Pydantic and ``lab_core``. They must not
import subprocess, sockets, requests/httpx, os process APIs, or perform I/O.
Conformance tests enforce this statically.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from lab_core.adapter_io import AdapterDescriptor

from lab_core import (
    CandidateSpec,
    CommandSpec,
    CompatibilityResult,
    ContextFeasibility,
    DeploymentRecipe,
    EngineCapabilityManifest,
    EngineId,
    ExecutionPlan,
    HardwareSnapshot,
    MicrobenchObservation,
    ModelArtifact,
    ModelMetadata,
    ProcessOutput,
    RawEvidence,
    RegisteredBinary,
    SandboxPaths,
    SearchSpaceRequest,
    SearchSpaceSpec,
    ServerExecutionPlan,
    ServingObservation,
)

from .results import ValidatedEvidence


@runtime_checkable
class InferenceAdapter(Protocol):
    """Contract for a pure engine adapter (schema-versioned)."""

    adapter_id: ClassVar[EngineId]
    adapter_schema: ClassVar[str]

    def describe(self) -> AdapterDescriptor: ...

    def build_probe_commands(self, binary: RegisteredBinary) -> tuple[CommandSpec, ...]: ...

    def parse_probe_output(
        self, outputs: tuple[ProcessOutput, ...], binary: RegisteredBinary
    ) -> EngineCapabilityManifest: ...

    def inspect_model(self, artifact: ModelArtifact, engine: EngineCapabilityManifest) -> ModelMetadata: ...

    def check_compatibility(
        self,
        model: ModelArtifact,
        engine: EngineCapabilityManifest,
        hardware: HardwareSnapshot,
    ) -> CompatibilityResult: ...

    def search_space(self, request: SearchSpaceRequest) -> SearchSpaceSpec: ...

    def validate_candidate(
        self, candidate: CandidateSpec, engine: EngineCapabilityManifest
    ) -> tuple[str, ...]:
        """Return human-readable incompatibilities; never silently drop a flag."""
        ...

    def build_microbench_plan(
        self,
        candidate: CandidateSpec,
        sandbox: SandboxPaths,
        *,
        binary: RegisteredBinary,
        model: ModelArtifact,
        repetitions: int = 3,
    ) -> ExecutionPlan: ...

    def build_server_plan(
        self,
        candidate: CandidateSpec,
        sandbox: SandboxPaths,
        *,
        binary: RegisteredBinary,
        model: ModelArtifact,
        port: int,
    ) -> ServerExecutionPlan: ...

    def parse_microbench_evidence(
        self, evidence: RawEvidence, candidate: CandidateSpec
    ) -> MicrobenchObservation: ...

    def parse_server_evidence(
        self, status: RawEvidence, metrics: RawEvidence | None, candidate: CandidateSpec
    ) -> ServingObservation: ...

    def build_deployment_recipe(
        self,
        candidate: CandidateSpec,
        evidence: ValidatedEvidence,
        *,
        binary: RegisteredBinary,
        model: ModelArtifact,
        hardware: HardwareSnapshot,
    ) -> DeploymentRecipe: ...

    def assess_context_feasibility(
        self,
        candidate: CandidateSpec,
        engine: EngineCapabilityManifest,
        hardware: HardwareSnapshot,
    ) -> ContextFeasibility: ...
