"""A documented future-adapter conformance stub.

This is not a shipping engine. It exists to prove that a new adapter can be
registered and exercised through the same typed contract without changing the
optimizer, worker protocol or scoring code.
"""

from __future__ import annotations

import re
from typing import ClassVar

from lab_core.adapter_io import AdapterDescriptor
from lab_core.ids import sha256_text
from lab_core.search import DimensionKind, ParameterDimension
from lab_core.version import ADAPTER_SDK_VERSION

from lab_core import (
    Backend,
    CandidateSpec,
    CapabilityKind,
    CommandSpec,
    CompatibilityResult,
    ContextFeasibility,
    DeploymentRecipe,
    EngineCapabilityManifest,
    EngineId,
    EngineIdentity,
    ExecutionPlan,
    ExecutionStage,
    FeasibilityOutcome,
    HardwareSnapshot,
    ImpactClass,
    MicrobenchObservation,
    MicrobenchRow,
    ModelArtifact,
    ModelMetadata,
    ProcessOutput,
    RawEvidence,
    RecipeEngine,
    RecipeHardware,
    RecipeLaunch,
    RecipeModel,
    RecipeModelFile,
    RecipeRollback,
    RecipeValidationRefs,
    RegisteredBinary,
    SandboxPaths,
    SearchSpaceRequest,
    SearchSpaceSpec,
    ServerExecutionPlan,
    ServingObservation,
    stable_id,
    utcnow,
)

from ..base.parsing import descriptor, parse_json_document, probe_command
from ..base.protocol import InferenceAdapter
from ..base.results import ValidatedEvidence

_VERSION_RE = re.compile(r"mock-adapter\s+(?P<version>\S+)")


class MockFutureAdapter(InferenceAdapter):
    adapter_id: ClassVar[EngineId] = EngineId.MOCK_FUTURE
    adapter_schema: ClassVar[str] = ADAPTER_SDK_VERSION

    def describe(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            adapter_id=self.adapter_id,
            adapter_schema=self.adapter_schema,
            supported_models=("mock-pack",),
            requires_native_binary=True,
            notes=(
                "Conformance stub only. No production inference engine is shipped under this identifier.",
            ),
        )

    def build_probe_commands(self, binary: RegisteredBinary) -> tuple[CommandSpec, ...]:
        return (probe_command(binary, ("--version",), "text/plain; schema=mock.version/v1"),)

    def parse_probe_output(
        self, outputs: tuple[ProcessOutput, ...], binary: RegisteredBinary
    ) -> EngineCapabilityManifest:
        text = "\n".join(output.stdout + "\n" + output.stderr for output in outputs)
        match = _VERSION_RE.search(text)
        if not match:
            raise ValueError("could not parse mock adapter version")
        return EngineCapabilityManifest(
            engine=EngineIdentity(
                engine_id=EngineId.MOCK_FUTURE,
                adapter_schema=self.adapter_schema,
                version=match.group("version"),
                build=binary.build or match.group("version"),
                backend=Backend.CUDA,
                executable_id=binary.executable_id,
                executable_sha256=binary.sha256,
            ),
            backend=Backend.CUDA,
            probed_at=utcnow(),
            descriptors=(
                descriptor(
                    "--workers", CapabilityKind.INT, minimum=1, maximum=64, default=4, impact=ImpactClass.P1
                ),
                descriptor(
                    "--max-context",
                    CapabilityKind.INT,
                    minimum=512,
                    maximum=131072,
                    default=4096,
                    impact=ImpactClass.P0,
                ),
            ),
            help_sha256=sha256_text(text),
        )

    def inspect_model(self, artifact: ModelArtifact, engine: EngineCapabilityManifest) -> ModelMetadata:
        return ModelMetadata(
            architecture=artifact.architecture,
            model_type="mock-pack",
            context_train_tokens=artifact.metadata_context_tokens,
            tokenizer_id=artifact.tokenizer_id,
        )

    def check_compatibility(
        self, model: ModelArtifact, engine: EngineCapabilityManifest, hardware: HardwareSnapshot
    ) -> CompatibilityResult:
        return CompatibilityResult(
            compatible=bool(hardware.gpus),
            engine_id=EngineId.MOCK_FUTURE,
            model_id=model.model_id,
            checked_at=utcnow(),
            reasons=() if hardware.gpus else ("mock adapter requires a GPU",),
            support="supported" if hardware.gpus else "unsupported",
        )

    def search_space(self, request: SearchSpaceRequest) -> SearchSpaceSpec:
        return SearchSpaceSpec(
            engine_id=EngineId.MOCK_FUTURE,
            dimensions=(
                ParameterDimension(name="workers", kind=DimensionKind.INT, minimum=1, maximum=32, default=4),
            ),
            fixed_parameters={"max_context": request.context_tokens},
            max_proposals=32,
        )

    def validate_candidate(
        self, candidate: CandidateSpec, engine: EngineCapabilityManifest
    ) -> tuple[str, ...]:
        errors: list[str] = []
        for name, value in candidate.parameters.items():
            if name not in {"workers", "max_context"}:
                errors.append(f"unknown mock parameter {name!r}")
            elif isinstance(value, bool) or not isinstance(value, int):
                errors.append(f"{name} must be an integer")
        return tuple(errors)

    def build_microbench_plan(
        self,
        candidate: CandidateSpec,
        sandbox: SandboxPaths,
        *,
        binary: RegisteredBinary,
        model: ModelArtifact,
        repetitions: int = 3,
    ) -> ExecutionPlan:
        prompt = max(1, int(candidate.context) // 4)
        argv = (
            "--prompt-tokens",
            str(prompt),
            "--max-new",
            "256",
            "--max-context",
            str(int(candidate.context)),
            "--repetitions",
            str(repetitions),
            "--output",
            "json",
        )
        command = CommandSpec(
            executable_id=binary.executable_id,
            executable_sha256=binary.sha256,
            argv=argv,
            env={"LC_ALL": "C"},
            cwd=sandbox.work_dir,
            timeout_seconds=600,
            stdout_schema="mock.microbench.json/v1",
        )
        return ExecutionPlan(
            engine_id=EngineId.MOCK_FUTURE,
            candidate_digest=candidate.semantic_key(),
            sandbox=sandbox,
            stages=(ExecutionStage(name="mock-microbench", command=command),),
            expected_observation_schema="lab.native_microbench/v1",
        )

    def build_server_plan(
        self,
        candidate: CandidateSpec,
        sandbox: SandboxPaths,
        *,
        binary: RegisteredBinary,
        model: ModelArtifact,
        port: int,
    ) -> ServerExecutionPlan:
        command = CommandSpec(
            executable_id=binary.executable_id,
            executable_sha256=binary.sha256,
            argv=(
                "--serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--max-context",
                str(int(candidate.context)),
            ),
            env={"LC_ALL": "C"},
            cwd=sandbox.work_dir,
            timeout_seconds=600,
            stdout_schema="text/plain",
        )
        return ServerExecutionPlan(
            engine_id=EngineId.MOCK_FUTURE,
            candidate_digest=candidate.semantic_key(),
            sandbox=sandbox,
            start=ExecutionStage(name="mock-server", command=command),
            bind_host="127.0.0.1",
            port_range_start=port,
            port_range_end=port,
            health_path="/health",
            readiness_timeout_seconds=120,
        )

    def parse_microbench_evidence(
        self, evidence: RawEvidence, candidate: CandidateSpec
    ) -> MicrobenchObservation:
        document = parse_json_document(evidence.text)
        prefill = float(document["prefill_tokens_per_sec"])
        decode = float(document["decode_tokens_per_sec"])
        context = int(document.get("context", candidate.context))
        return MicrobenchObservation(
            engine_id=EngineId.MOCK_FUTURE.value,
            rows=(
                MicrobenchRow(test=f"pp{context // 4}", n_prompt=context // 4, n_gen=0, avg_ts=prefill),
                MicrobenchRow(test="tg16", n_prompt=0, n_gen=16, avg_ts=decode),
            ),
            raw_sha256=sha256_text(evidence.text),
        )

    def parse_server_evidence(
        self, status: RawEvidence, metrics: RawEvidence | None, candidate: CandidateSpec
    ) -> ServingObservation:
        document = parse_json_document(status.text)
        return ServingObservation(
            engine_id=EngineId.MOCK_FUTURE.value,
            status_sha256=sha256_text(status.text),
            metrics_sha256=sha256_text(metrics.text) if metrics else None,
            context_configured=int(candidate.context),
            context_effective=int(document.get("context", candidate.context)),
            prefill_tokens_per_sec=document.get("prefill_tokens_per_sec"),
            decode_tokens_per_sec=document.get("decode_tokens_per_sec"),
            time_to_first_token_ms=document.get("time_to_first_token_ms"),
            total_latency_ms=document.get("total_latency_ms"),
            unavailable_reasons={"time_to_first_token_ms": "mock evidence only"},
        )

    def build_deployment_recipe(
        self,
        candidate: CandidateSpec,
        evidence: ValidatedEvidence,
        *,
        binary: RegisteredBinary,
        model: ModelArtifact,
        hardware: HardwareSnapshot,
    ) -> DeploymentRecipe:
        if not evidence.validated:
            raise ValueError("recipe requires validated evidence")
        gpu = hardware.gpus[0]
        peak = next(
            (
                obs.metrics.gpu_vram_peak_bytes
                for obs in evidence.observations
                if obs.metrics.gpu_vram_peak_bytes
            ),
            None,
        )
        if peak is None:
            raise ValueError("recipe requires measured peak VRAM")
        recipe_id = stable_id(
            "recipe", candidate.candidate_id, model.artifact_digest, binary.sha256, int(candidate.context)
        )
        return DeploymentRecipe(
            id=recipe_id,
            engine=RecipeEngine(
                id=EngineId.MOCK_FUTURE,
                version=binary.version or "mock",
                build=binary.build or "mock",
                executable=binary.path,
                sha256=binary.sha256,
            ),
            model=RecipeModel(
                id=model.model_id,
                files=tuple(
                    RecipeModelFile(path=item.path, sha256=item.sha256, size_bytes=item.size_bytes)
                    for item in model.files
                    if item.sha256 is not None
                ),
                artifact_digest=model.artifact_digest,
            ),
            hardware=RecipeHardware(
                gpu_model=gpu.name,
                gpu_uuid=gpu.uuid,
                min_vram_bytes=peak,
                worker_id=candidate.worker_id,
            ),
            objective=evidence.objective,
            context_tokens=int(candidate.context),
            launch=RecipeLaunch(
                executable=binary.path, argv=("--serve", "--max-context", str(int(candidate.context)))
            ),
            validation=RecipeValidationRefs(
                protocol=evidence.observations[0].protocol,
                experiment_id=evidence.experiment_id,
                metrics_ref=evidence.metrics_ref,
                validated_at=evidence.validated_at,
                claim_scope=(f"{int(candidate.context) // 1024}K",),
            ),
            rollback=RecipeRollback(),
            notes=("mock adapter conformance fixture",),
        )

    def assess_context_feasibility(
        self, candidate: CandidateSpec, engine: EngineCapabilityManifest, hardware: HardwareSnapshot
    ) -> ContextFeasibility:
        return ContextFeasibility(context=candidate.context, status=FeasibilityOutcome.UNKNOWN)
