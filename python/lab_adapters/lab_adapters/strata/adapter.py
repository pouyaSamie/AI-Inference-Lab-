"""Pure Strata adapter for the installed 0.1.44.x runtime.

Observed interface (see docs/PHASE_0_FINDINGS.md):
  * ``strata --version`` and ``strata generate`` in the native binary.
  * A Python OpenAI-compatible server (``serve/server.py``) launched with a
    JSON profile; it exposes /health, /v1/status and /metrics.
  * The ``models/doctor/engine calibrate/bench run`` CLI described in the PRD
    is **not** present in this installed build.

The adapter therefore refuses to invent a native benchmark command and models
the available serving lane explicitly. Tokenizer-verified context validation
and the Lab Custom Protocol belong to Phase 4.
"""

from __future__ import annotations

import json
import re
from typing import ClassVar

from lab_core import (
    Backend,
    CandidateSpec,
    CapabilityKind,
    CapabilityProvenance,
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
    GeneratedFile,
    HardwareSnapshot,
    ImpactClass,
    MicrobenchObservation,
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
    SupportLevel,
    UnsupportedCapabilityError,
    utcnow,
    stable_id,
)
from lab_core.adapter_io import AdapterDescriptor
from lab_core.ids import sha256_text
from lab_core.search import DimensionKind, ParameterDimension
from lab_core.version import ADAPTER_SDK_VERSION

from ..base.parsing import descriptor, observed_flags, parse_json_document, probe_command, require_flags, server_readiness
from ..base.results import ValidatedEvidence
from ..base.protocol import InferenceAdapter

_VERSION_RE = re.compile(r"^strata\s+(?P<version>\S+)\s*$", re.MULTILINE)


def _int(parameters: dict[str, object], key: str, default: int) -> int:
    value = parameters.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"parameter {key!r} must be an integer")
    return value


def _bool(parameters: dict[str, object], key: str, default: bool) -> bool:
    value = parameters.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"parameter {key!r} must be a boolean")
    return value


class StrataAdapter(InferenceAdapter):
    adapter_id: ClassVar[EngineId] = EngineId.STRATA
    adapter_schema: ClassVar[str] = ADAPTER_SDK_VERSION

    def describe(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            adapter_id=self.adapter_id,
            adapter_schema=self.adapter_schema,
            supported_models=("strata-pack",),
            requires_native_binary=True,
            notes=(
                "Installed build exposes `strata generate` and a Python OpenAI-compatible server.",
                "No `models list`, `doctor`, `engine calibrate` or `bench run` subcommands were observed.",
                "Native benchmark claims are refused; the serving lane is a Lab Custom Protocol.",
            ),
        )

    def build_probe_commands(self, binary: RegisteredBinary) -> tuple[CommandSpec, ...]:
        return (
            probe_command(binary, ("--version",), "text/plain; schema=strata.version/v1"),
            probe_command(binary, ("--help",), "text/plain; schema=strata.generate-help/v1"),
        )

    def parse_probe_output(
        self, outputs: tuple[ProcessOutput, ...], binary: RegisteredBinary
    ) -> EngineCapabilityManifest:
        version_text = "\n".join(output.stdout + "\n" + output.stderr for output in outputs)
        help_text = "\n".join(output.stdout for output in outputs)
        match = _VERSION_RE.search(version_text)
        if not match:
            raise ValueError("could not parse `strata --version`; refusing to guess capabilities")
        flags = observed_flags(help_text)
        require_flags(flags, ("--pack", "--max-context"))
        engine = EngineIdentity(
            engine_id=EngineId.STRATA,
            adapter_schema=self.adapter_schema,
            version=match.group("version"),
            build=binary.build or match.group("version"),
            backend=binary.backend,
            executable_id=binary.executable_id,
            executable_sha256=binary.sha256,
        )
        spec: dict[str, tuple[CapabilityKind, dict[str, object]]] = {
            "--max-context": (CapabilityKind.INT, {"minimum": 512, "maximum": 131072, "default": 4096}),
            "--max-new": (CapabilityKind.INT, {"minimum": 1, "maximum": 131072, "default": 16}),
            "--kv": (
                CapabilityKind.ENUM,
                {
                    "legal_values": ("fp16", "int8", "q4_0", "k8v4"),
                    "default": "fp16",
                    "quality_risk": True,
                    "provenance": CapabilityProvenance.OBSERVED_CLI,
                },
            ),
            "--expert-cache": (CapabilityKind.STRING, {"default": "auto"}),
            "--prefill": (CapabilityKind.STRING, {"default": "auto"}),
            "--spec": (CapabilityKind.INT, {"minimum": 0, "maximum": 16, "default": 4}),
            "--spec-min-p": (CapabilityKind.FLOAT, {"minimum": 0.0, "maximum": 1.0, "default": 0.5}),
            "--pool-workers": (CapabilityKind.INT, {"minimum": 1, "maximum": 256, "default": 0}),
            "--kv-resident": (CapabilityKind.INT, {"minimum": 20480, "maximum": 131072}),
            "--kv-grow": (CapabilityKind.BOOL, {"default": False}),
            "--resident-experts": (CapabilityKind.BOOL, {"default": False}),
            "--mmap-experts": (CapabilityKind.BOOL, {"default": False}),
            "--batch": (CapabilityKind.INT, {"minimum": 1, "maximum": 8, "default": 1}),
            "--serve": (CapabilityKind.BOOL, {"default": False}),
            "--ple-io": (CapabilityKind.ENUM, {"legal_values": ("direct", "mmap", "ram"), "default": "direct"}),
            "--gpu": (CapabilityKind.STRING, {"default": "0"}),
        }
        descriptors = []
        for key, (kind, extra) in spec.items():
            if key not in flags:
                continue
            impact = ImpactClass.P0 if key in {"--max-context", "--kv", "--expert-cache"} else ImpactClass.P1
            descriptors.append(descriptor(key, kind, impact=impact, **extra))  # type: ignore[arg-type]
        return EngineCapabilityManifest(
            engine=engine,
            backend=binary.backend,
            probed_at=utcnow(),
            descriptors=tuple(descriptors),
            help_sha256=sha256_text(help_text),
            version_output_sha256=sha256_text(version_text),
            notes=(
                "Observed flags come from `strata --help` (generate surface).",
                "Serving is launched through serve/server.py with a JSON profile.",
            ),
        )

    def inspect_model(self, artifact: ModelArtifact, engine: EngineCapabilityManifest) -> ModelMetadata:
        pack_path = artifact.metadata.get("pack_path")
        if not isinstance(pack_path, str):
            raise ValueError("Strata model artifact must record its pack path in metadata")
        return ModelMetadata(
            architecture=artifact.architecture,
            model_type="strata-pack",
            quantization=artifact.quantization,
            context_train_tokens=artifact.metadata_context_tokens,
            moe=bool(artifact.metadata.get("moe", True)),
            tokenizer_id=artifact.tokenizer_id,
            shard_count=len(artifact.files) or 1,
            attributes={
                "pack_path": pack_path,
                "native": artifact.metadata.get("native"),
                "ple_gguf": artifact.metadata.get("ple_gguf"),
                "mtp": artifact.metadata.get("mtp"),
                "expert_profile": artifact.metadata.get("expert_profile"),
                "server_script": artifact.metadata.get("server_script"),
                "engine_executable": artifact.metadata.get("engine_executable"),
                "engine_sha256": artifact.metadata.get("engine_sha256"),
                "base_args": artifact.metadata.get("base_args", []),
            },
        )

    def check_compatibility(
        self, model: ModelArtifact, engine: EngineCapabilityManifest, hardware: HardwareSnapshot
    ) -> CompatibilityResult:
        reasons: list[str] = []
        if model.metadata.get("model_type") not in (None, "strata-pack"):
            reasons.append("model is not marked as a Strata-compatible pack")
        if not model.metadata.get("pack_path"):
            reasons.append("model artifact has no pack_path metadata")
        if not hardware.gpus:
            reasons.append("Strata serving requires a GPU")
        warnings: list[str] = []
        if not model.hashes_complete():
            warnings.append("model artifact hashes are incomplete; recipes cannot be approved")
        support = "conditional" if reasons or warnings else "supported"
        return CompatibilityResult(
            compatible=not reasons,
            engine_id=EngineId.STRATA,
            model_id=model.model_id,
            checked_at=utcnow(),
            reasons=tuple(reasons),
            warnings=tuple(warnings),
            support=support,  # type: ignore[arg-type]
        )

    def search_space(self, request: SearchSpaceRequest) -> SearchSpaceSpec:
        return SearchSpaceSpec(
            engine_id=EngineId.STRATA,
            dimensions=(
                ParameterDimension(name="kv", kind=DimensionKind.CATEGORICAL, choices=("fp16", "int8", "q4_0", "k8v4"), default="fp16", quality_risk=True),
                ParameterDimension(name="expert_cache", kind=DimensionKind.CATEGORICAL, choices=("auto", 0, 16, 32, 64), default="auto"),
                ParameterDimension(name="prefill", kind=DimensionKind.CATEGORICAL, choices=("auto", 1024, 2048, 4096), default="auto"),
                ParameterDimension(name="spec", kind=DimensionKind.INT, minimum=0, maximum=8, default=4),
                ParameterDimension(name="pool_workers", kind=DimensionKind.INT, minimum=1, maximum=32, default=15),
                ParameterDimension(name="resident_experts", kind=DimensionKind.CATEGORICAL, choices=(False, True), default=False),
                ParameterDimension(name="mmap_experts", kind=DimensionKind.CATEGORICAL, choices=(False, True), default=False),
            ),
            fixed_parameters={"max_context": request.context_tokens},
            constraints=("Only flags observed in the installed build are emitted.",),
            max_proposals=256,
            notes=("Strata's native calibration is not a benchmark protocol and is not used here.",),
        )

    def validate_candidate(self, candidate: CandidateSpec, engine: EngineCapabilityManifest) -> tuple[str, ...]:
        mapping = {
            "kv": "--kv",
            "expert_cache": "--expert-cache",
            "prefill": "--prefill",
            "spec": "--spec",
            "spec_min_p": "--spec-min-p",
            "pool_workers": "--pool-workers",
            "resident_experts": "--resident-experts",
            "mmap_experts": "--mmap-experts",
            "max_context": "--max-context",
            "kv_resident": "--kv-resident",
            "kv_grow": "--kv-grow",
            "batch": "--batch",
            "ple_io": "--ple-io",
            "gpu": "--gpu",
        }
        errors: list[str] = []
        for name, value in candidate.parameters.items():
            flag = mapping.get(name)
            if flag is None:
                errors.append(f"unknown Strata parameter {name!r}")
                continue
            capability = engine.descriptor(flag)
            if capability is None:
                errors.append(f"parameter {name!r} requires {flag}, absent from the installed build")
                continue
            if capability.support is not SupportLevel.SUPPORTED:
                errors.append(f"parameter {name!r} is not supported by the installed build")
                continue
            if capability.kind is CapabilityKind.ENUM and value not in capability.legal_values:
                errors.append(f"{name}={value!r} is not one of {capability.legal_values}")
            if capability.kind is CapabilityKind.INT:
                if isinstance(value, bool) or not isinstance(value, int):
                    errors.append(f"{name} must be an integer")
                elif capability.minimum is not None and value < capability.minimum:
                    errors.append(f"{name}={value} is below {capability.minimum}")
                elif capability.maximum is not None and value > capability.maximum:
                    errors.append(f"{name}={value} is above {capability.maximum}")
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
        raise UnsupportedCapabilityError(
            "the installed Strata build exposes no benchmark protocol; Phase 4 must run the uniform API lane",
            details={"observed_commands": ["strata generate"], "missing": ["strata bench run", "strata engine calibrate"]},
        )

    def _profile(self, candidate: CandidateSpec, model: ModelArtifact) -> dict[str, object]:
        pack_path = model.metadata.get("pack_path")
        engine_executable = model.metadata.get("engine_executable")
        tokenizer = model.metadata.get("tokenizer_path")
        if not isinstance(pack_path, str) or not isinstance(engine_executable, str):
            raise ValueError("Strata model metadata must include pack_path and engine_executable")
        base_args = model.metadata.get("base_args")
        if not isinstance(base_args, list) or not all(isinstance(item, str) for item in base_args):
            base_args = []
        args = [
            item
            for item in base_args
            if item not in {"--max-context", "--kv", "--expert-cache", "--prefill", "--spec", "--pool-workers"}
        ]
        args.extend(["--pack", pack_path])
        args.extend(["--max-context", str(int(candidate.context))])
        if model.metadata.get("native"):
            args.extend(["--native", str(model.metadata["native"])])
        if model.metadata.get("ple_gguf"):
            args.extend(["--ple-gguf", str(model.metadata["ple_gguf"])])
        if model.metadata.get("mtp"):
            args.extend(["--mtp", str(model.metadata["mtp"])])
        if model.metadata.get("expert_profile"):
            args.extend(["--expert-profile", str(model.metadata["expert_profile"])])
        params = candidate.parameters
        if "kv" in params:
            args.extend(["--kv", str(params["kv"])])
        if "expert_cache" in params:
            args.extend(["--expert-cache", str(params["expert_cache"])])
        if "prefill" in params:
            args.extend(["--prefill", str(params["prefill"])])
        if "spec" in params:
            args.extend(["--spec", str(params["spec"])])
        if "pool_workers" in params:
            args.extend(["--pool-workers", str(params["pool_workers"])])
        if _bool(params, "resident_experts", False):
            args.append("--resident-experts")
        if _bool(params, "mmap_experts", False):
            args.append("--mmap-experts")
        profile: dict[str, object] = {
            "exe": engine_executable,
            "args": args,
            "cwd": model.metadata.get("cwd") or ".",
            "model_name": model.metadata.get("model_name") or model.model_id,
            "gpu": _int(params, "gpu", 0),
            "lib_dirs": model.metadata.get("lib_dirs", []),
        }
        if isinstance(tokenizer, str):
            profile["tokenizer"] = tokenizer
        return profile

    def build_server_plan(
        self,
        candidate: CandidateSpec,
        sandbox: SandboxPaths,
        *,
        binary: RegisteredBinary,
        model: ModelArtifact,
        port: int,
    ) -> ServerExecutionPlan:
        server_script = model.metadata.get("server_script")
        if not isinstance(server_script, str):
            raise ValueError("Strata model metadata must include the observed server_script path")
        profile = self._profile(candidate, model)
        content = json.dumps(profile, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        profile_file = GeneratedFile(relative_path="strata-profile.json", content=content)
        profile_path = f"{sandbox.work_dir.rstrip('/')}/{profile_file.relative_path}"
        args = (
            server_script,
            "--engine",
            "strata",
            "--config",
            profile_path,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        )
        command = CommandSpec(
            executable_id=binary.executable_id,
            executable_sha256=binary.sha256,
            argv=args,
            env={"LC_ALL": "C", "LANG": "C", "CUDA_DEVICE_ORDER": "PCI_BUS_ID"},
            cwd=sandbox.work_dir,
            timeout_seconds=7200,
            readiness=server_readiness("/health", timeout=300),
            stdout_schema="text/plain",
        )
        return ServerExecutionPlan(
            engine_id=EngineId.STRATA,
            candidate_digest=candidate.semantic_key(),
            sandbox=sandbox,
            start=ExecutionStage(name="strata-server", command=command),
            bind_host="127.0.0.1",
            port_range_start=port,
            port_range_end=port,
            health_path="/health",
            metrics_path="/metrics",
            readiness_timeout_seconds=300,
        )

    def parse_microbench_evidence(self, evidence: RawEvidence, candidate: CandidateSpec) -> MicrobenchObservation:
        raise UnsupportedCapabilityError(
            "the installed Strata build exposes no native microbenchmark evidence schema",
            details={"evidence_content_type": evidence.content_type},
        )

    def parse_server_evidence(
        self, status: RawEvidence, metrics: RawEvidence | None, candidate: CandidateSpec
    ) -> ServingObservation:
        document = parse_json_document(status.text)
        if not isinstance(document, dict):
            raise ValueError("Strata /v1/status evidence must be a JSON object")
        timings = document.get("last_timings")
        context = document.get("context")
        unavailable: dict[str, str] = {}
        prefill = decode = ttft = total = None
        prompt_n = output_n = None
        cache_hit = None
        if isinstance(timings, dict):
            prefill = timings.get("prompt_per_second")
            decode = timings.get("predicted_per_second")
            prompt_n = timings.get("prompt_n")
            output_n = timings.get("predicted_n")
            cache_n = timings.get("cache_n")
            cache_hit = bool(cache_n) if isinstance(cache_n, int) else None
            if timings.get("prompt_ms") is not None:
                total = float(timings["prompt_ms"]) + float(timings.get("predicted_ms") or 0.0)
            unavailable["time_to_first_token_ms"] = "client-measured TTFT is not present in /v1/status"
        else:
            for key in ("prefill_tokens_per_sec", "decode_tokens_per_sec", "total_latency_ms"):
                unavailable[key] = "no last_timings block was present"
        effective = None
        if isinstance(context, dict):
            effective = context.get("native") or context.get("max_positions")
        machine = document.get("machine")
        gpu = machine.get("gpu") if isinstance(machine, dict) else None
        vram = None
        util = None
        temp = None
        if isinstance(gpu, dict):
            used = gpu.get("used_mib")
            if isinstance(used, (int, float)):
                vram = int(used * 1024 * 1024)
            util = gpu.get("util_pct")
            temp = gpu.get("temp_c")
        return ServingObservation(
            engine_id=EngineId.STRATA.value,
            status_sha256=sha256_text(status.text),
            metrics_sha256=sha256_text(metrics.text) if metrics else None,
            context_configured=int(candidate.context),
            context_effective=int(effective) if isinstance(effective, int) else None,
            prefill_tokens_per_sec=float(prefill) if isinstance(prefill, (int, float)) else None,
            decode_tokens_per_sec=float(decode) if isinstance(decode, (int, float)) else None,
            time_to_first_token_ms=float(ttft) if ttft is not None else None,
            total_latency_ms=total,
            prompt_tokens=int(prompt_n) if isinstance(prompt_n, int) else None,
            output_tokens=int(output_n) if isinstance(output_n, int) else None,
            cache_hit=cache_hit,
            gpu_vram_used_bytes=vram,
            gpu_utilization=float(util) if isinstance(util, (int, float)) else None,
            gpu_temperature_c=float(temp) if isinstance(temp, (int, float)) else None,
            unavailable_reasons=unavailable,
            warnings=(
                "This serving evidence is a Lab Custom Protocol measurement, not a Strata standard benchmark score.",
                "Native calibration output is not treated as an optimum.",
            ),
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
            raise ValueError("a deployment recipe requires validated evidence")
        if not model.hashes_complete():
            raise ValueError("model artifact hashes are incomplete")
        engine_executable = model.metadata.get("engine_executable")
        engine_sha256 = model.metadata.get("engine_sha256")
        server_script = model.metadata.get("server_script")
        if not isinstance(engine_executable, str) or not isinstance(engine_sha256, str) or not isinstance(server_script, str):
            raise ValueError("Strata recipe requires engine_executable, engine_sha256 and server_script metadata")
        if not hardware.gpus:
            raise ValueError("Strata recipe requires a GPU hardware snapshot")
        peaks = [obs.metrics.gpu_vram_peak_bytes for obs in evidence.observations if obs.metrics.gpu_vram_peak_bytes]
        if not peaks:
            raise ValueError("Strata recipe requires measured peak VRAM, not an estimate")
        gpu = hardware.gpus[0]
        profile = self._profile(candidate, model)
        profile_content = json.dumps(profile, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        recipe_id = stable_id("recipe", candidate.candidate_id, model.artifact_digest, engine_sha256, int(candidate.context))
        return DeploymentRecipe(
            id=recipe_id,
            engine=RecipeEngine(
                id=EngineId.STRATA,
                version=binary.version or "unknown",
                build=binary.build or "unknown",
                executable=engine_executable,
                sha256=engine_sha256,
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
                min_vram_bytes=max(peaks),
                driver_version=gpu.driver_version,
                compute_capability=gpu.compute_capability,
                worker_id=candidate.worker_id,
            ),
            objective=evidence.objective,
            context_tokens=int(candidate.context),
            launch=RecipeLaunch(executable=binary.path, argv=(server_script, "--engine", "strata", "--config", "strata-profile.json", "--host", "127.0.0.1")),
            validation=RecipeValidationRefs(
                protocol=evidence.observations[0].protocol,
                experiment_id=evidence.experiment_id,
                metrics_ref=evidence.metrics_ref,
                confidence_ref=evidence.confidence_ref,
                claim_scope=(f"{int(candidate.context) // 1024}K",),
                validated_at=evidence.validated_at,
            ),
            rollback=RecipeRollback(required_smoke_tests=("ready", "one_token", "profile_identity")),
            notes=(
                "Strata native profile is generated in the experiment sandbox; original operator profiles are never modified.",
                f"profile_sha256={sha256_text(profile_content)}",
            ),
        )

    def assess_context_feasibility(
        self, candidate: CandidateSpec, engine: EngineCapabilityManifest, hardware: HardwareSnapshot
    ) -> ContextFeasibility:
        return ContextFeasibility(
            context=candidate.context,
            status=FeasibilityOutcome.UNKNOWN,
            reason=(
                "Strata full-context feasibility requires a worker-owned managed server allocation test; "
                "the native generate surface is not a serving-context proof."
            ),
        )
