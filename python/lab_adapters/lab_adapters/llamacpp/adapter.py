"""Pure llama.cpp adapter for an observed, versioned native build.

The adapter implements capability discovery from captured ``--version`` and
``--help`` output, typed parameter validation, argv construction for
``llama-bench``/``llama-server``, and parsing of native evidence. It performs
no I/O and never claims an unobserved flag is supported.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, ClassVar

from lab_core.adapter_io import AdapterDescriptor
from lab_core.ids import sha256_text
from lab_core.search import ConditionOperator, DimensionKind, ParameterDimension, SearchCondition
from lab_core.version import ADAPTER_SDK_VERSION

from lab_core import (
    Backend,
    BenchmarkObservation,
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
    HardwareSnapshot,
    ImpactClass,
    MicrobenchObservation,
    MicrobenchRow,
    ModelArtifact,
    ModelMetadata,
    Objective,
    ProcessOutput,
    RawEvidence,
    ReadinessKind,
    ReadinessPredicate,
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
    WorkloadSuite,
    stable_id,
    utcnow,
)

from ..base.parsing import (
    descriptor,
    observed_flags,
    parse_json_document,
    probe_command,
    require_flags,
    server_readiness,
    validate_capability_value,
)
from ..base.protocol import InferenceAdapter
from ..base.results import ValidatedEvidence

_VERSION_RE = re.compile(
    r"version:\s*(?P<version>\S+)\s*\(build\s+(?P<build>\d+),\s*commit\s+(?P<commit>[0-9a-fA-F]+)\)"
)
_BUILT_RE = re.compile(r"built with\s+(?P<compiler>.+?)\s+for\s+(?P<platform>\S+)")
_CUDA_RE = re.compile(r"found\s+(?P<count>\d+)\s+CUDA devices", re.IGNORECASE)


def _as_int(parameters: Mapping[str, object], key: str, default: int) -> int:
    value = parameters.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"parameter {key!r} must be an integer")
    return value


def _as_str(parameters: dict[str, object], key: str, default: str) -> str:
    value = parameters.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"parameter {key!r} must be a string")
    return value


def _as_bool(parameters: Mapping[str, object], key: str, default: bool) -> bool:
    value = parameters.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"parameter {key!r} must be a boolean")
    return value


class LlamaCppAdapter(InferenceAdapter):
    adapter_id: ClassVar[EngineId] = EngineId.LLAMACPP
    adapter_schema: ClassVar[str] = ADAPTER_SDK_VERSION

    def describe(self) -> AdapterDescriptor:
        return AdapterDescriptor(
            adapter_id=self.adapter_id,
            adapter_schema=self.adapter_schema,
            supported_models=("gguf",),
            requires_native_binary=True,
            notes=(
                "Native lane uses llama-bench; serving lane uses a worker-owned llama-server.",
                "Capabilities are derived from captured --help/--version output for the pinned build.",
            ),
        )

    # ------------------------------------------------------------------ probe
    def build_probe_commands(self, binary: RegisteredBinary) -> tuple[CommandSpec, ...]:
        return (
            probe_command(binary, ("--version",), "text/plain; schema=llamacpp.version/v1"),
            probe_command(binary, ("--help",), "text/plain; schema=llamacpp.help/v1"),
        )

    def parse_probe_output(
        self, outputs: tuple[ProcessOutput, ...], binary: RegisteredBinary
    ) -> EngineCapabilityManifest:
        version_text = "\n".join(output.stdout + "\n" + output.stderr for output in outputs)
        server_outputs = tuple(output for output in outputs if "bench" not in output.command_id.lower())
        bench_outputs = tuple(output for output in outputs if "bench" in output.command_id.lower())
        # A caller that supplies only one probe pair (for example the simulated
        # inventory or a unit test) is treated as describing both binaries. The
        # real worker uses distinct ``probe-llama-server-*`` and
        # ``probe-llama-bench-*`` command IDs.
        if not bench_outputs:
            bench_outputs = outputs
        if not server_outputs:
            server_outputs = outputs
        server_help = "\n".join(output.stdout + "\n" + output.stderr for output in server_outputs)
        bench_help = "\n".join(output.stdout + "\n" + output.stderr for output in bench_outputs)
        help_text = f"{server_help}\n{bench_help}"
        match = _VERSION_RE.search(version_text)
        if not match:
            raise ValueError("could not parse llama.cpp version output; refusing to guess capabilities")
        built = _BUILT_RE.search(version_text)
        backend = binary.backend
        if backend is Backend.UNKNOWN and _CUDA_RE.search(version_text):
            backend = Backend.CUDA
        engine = EngineIdentity(
            engine_id=EngineId.LLAMACPP,
            adapter_schema=self.adapter_schema,
            version=match.group("version"),
            build=match.group("build"),
            backend=backend,
            executable_id=binary.executable_id,
            executable_sha256=binary.sha256,
            source_commit=match.group("commit"),
        )
        server_flags = observed_flags(server_help)
        bench_flags = observed_flags(bench_help)
        require_flags(server_flags, ("--model", "--ctx-size", "--host", "--port"))
        require_flags(
            bench_flags,
            (
                "--model",
                "--n-prompt",
                "--n-gen",
                "--n-depth",
                "--repetitions",
                "--output",
            ),
        )
        flags = server_flags | bench_flags
        descriptors = []
        spec: dict[str, tuple[CapabilityKind, dict[str, Any]]] = {
            "--model": (CapabilityKind.STRING, {}),
            "--ctx-size": (CapabilityKind.INT, {"minimum": 512, "maximum": 131072, "default": 0}),
            "--n-gpu-layers": (CapabilityKind.INT, {"minimum": -1, "maximum": 4096, "default": -1}),
            "--threads": (CapabilityKind.INT, {"minimum": 1, "maximum": 256, "default": -1}),
            "--batch-size": (CapabilityKind.INT, {"minimum": 1, "maximum": 8192, "default": 2048}),
            "--ubatch-size": (CapabilityKind.INT, {"minimum": 1, "maximum": 4096, "default": 512}),
            "--reasoning": (CapabilityKind.ENUM, {"legal_values": ("on", "off", "auto"), "default": "auto"}),
            "--flash-attn": (CapabilityKind.ENUM, {"legal_values": ("on", "off", "auto"), "default": "auto"}),
            "--cache-type-k": (
                CapabilityKind.ENUM,
                {
                    "legal_values": ("f16", "bf16", "q8_0", "q4_0"),
                    "default": "f16",
                    "quality_risk": True,
                    "provenance": CapabilityProvenance.APPROVED_RULE,
                },
            ),
            "--cache-type-v": (
                CapabilityKind.ENUM,
                {
                    "legal_values": ("f16", "bf16", "q8_0", "q4_0"),
                    "default": "f16",
                    "quality_risk": True,
                    "provenance": CapabilityProvenance.APPROVED_RULE,
                },
            ),
            "--n-cpu-moe": (CapabilityKind.INT, {"minimum": 0, "maximum": 4096, "default": 0}),
            "--parallel": (CapabilityKind.INT, {"minimum": 1, "maximum": 64, "default": -1}),
            "--kv-unified": (CapabilityKind.BOOL, {"default": True}),
            "--kv-unified-per-slot": (CapabilityKind.INT, {"minimum": 512, "maximum": 131072}),
            "--load-mode": (
                CapabilityKind.ENUM,
                {"legal_values": ("auto", "none", "mmap", "mlock", "mmap+mlock", "dio"), "default": "auto"},
            ),
            "--split-mode": (
                CapabilityKind.ENUM,
                {"legal_values": ("none", "layer", "row", "tensor"), "default": "layer"},
            ),
            "--no-kv-offload": (CapabilityKind.BOOL, {"default": False}),
            "--metrics": (CapabilityKind.BOOL, {"default": False}),
            "--jinja": (CapabilityKind.BOOL, {"default": True}),
            "--host": (CapabilityKind.STRING, {"default": "127.0.0.1"}),
            "--port": (CapabilityKind.INT, {"minimum": 1024, "maximum": 65535, "default": 9931}),
            "--alias": (CapabilityKind.STRING, {}),
            "--repetitions": (CapabilityKind.INT, {"minimum": 1, "maximum": 20, "default": 5}),
            "--n-prompt": (CapabilityKind.INT, {"minimum": 1, "maximum": 131072, "default": 512}),
            "--n-gen": (CapabilityKind.INT, {"minimum": 1, "maximum": 131072, "default": 128}),
            "--n-depth": (CapabilityKind.INT, {"minimum": 0, "maximum": 131072, "default": 0}),
            "--output": (
                CapabilityKind.ENUM,
                {"legal_values": ("csv", "json", "jsonl", "md", "sql"), "default": "md"},
            ),
        }
        for key, (kind, extra) in spec.items():
            if key not in flags:
                continue
            impact = (
                ImpactClass.P0
                if key
                in {
                    "--model",
                    "--n-gpu-layers",
                    "--ctx-size",
                    "--flash-attn",
                    "--cache-type-k",
                    "--cache-type-v",
                }
                else ImpactClass.P1
            )
            descriptors.append(
                descriptor(
                    key,
                    kind,
                    impact=extra.pop("impact_class", impact),
                    **extra,
                )
            )
        return EngineCapabilityManifest(
            engine=engine,
            backend=backend,
            probed_at=utcnow(),
            descriptors=tuple(descriptors),
            help_sha256=sha256_text(help_text),
            version_output_sha256=sha256_text(version_text),
            notes=(
                f"compiler/platform: {built.group('compiler') if built else 'unknown'}",
                "Presence of a flag is observed; legal enum values are versioned approved "
                "rules where help omits them.",
                f"server_help_sha256={sha256_text(server_help)}",
                f"bench_help_sha256={sha256_text(bench_help)}",
                "Required server and llama-bench flags were checked against their respective "
                "help output before this manifest was accepted.",
            ),
        )

    # -------------------------------------------------------------- inventory
    def inspect_model(self, artifact: ModelArtifact, engine: EngineCapabilityManifest) -> ModelMetadata:
        architecture = artifact.architecture.lower()
        is_gguf = "gguf" in architecture or any(path.lower().endswith(".gguf") for path in artifact.path_map)
        if not is_gguf:
            raise ValueError(f"llama.cpp cannot load model {artifact.model_id!r}: not a GGUF artifact")
        moe = any(token in architecture for token in ("moe", "a3b", "a2b", "expert"))
        return ModelMetadata(
            architecture=artifact.architecture,
            model_type="gguf",
            quantization=artifact.quantization,
            context_train_tokens=artifact.metadata_context_tokens,
            moe=moe,
            expert_count=int(artifact.metadata["expert_count"])
            if isinstance(artifact.metadata.get("expert_count"), int)
            else None,
            tokenizer_id=artifact.tokenizer_id,
            shard_count=len(artifact.files) or 1,
            attributes={"hashes_complete": artifact.hashes_complete()},
        )

    def check_compatibility(
        self, model: ModelArtifact, engine: EngineCapabilityManifest, hardware: HardwareSnapshot
    ) -> CompatibilityResult:
        reasons: list[str] = []
        if "gguf" not in model.architecture.lower() and not any(
            path.lower().endswith(".gguf") for path in model.path_map
        ):
            reasons.append("model is not a GGUF artifact")
        missing = engine.require_supported(("--model", "--ctx-size"))
        if missing:
            reasons.append(f"engine flags missing: {missing}")
        if engine.backend is Backend.CUDA and not hardware.gpus:
            reasons.append("engine is a CUDA build but no GPU was reported")
        warnings: list[str] = []
        if not model.hashes_complete():
            warnings.append("model artifact hashes are incomplete; recipes cannot be approved")
        support = (
            "unsupported"
            if any("not a GGUF" in reason for reason in reasons)
            else ("conditional" if reasons or warnings else "supported")
        )
        return CompatibilityResult(
            compatible=not any("not a GGUF" in reason for reason in reasons),
            engine_id=EngineId.LLAMACPP,
            model_id=model.model_id,
            checked_at=utcnow(),
            reasons=tuple(reasons),
            warnings=tuple(warnings),
            support=support,
        )

    # ---------------------------------------------------------------- search
    def search_space(self, request: SearchSpaceRequest) -> SearchSpaceSpec:
        dimensions: list[ParameterDimension] = [
            ParameterDimension(
                name="gpu_layers",
                kind=DimensionKind.CATEGORICAL,
                choices=(-1, 0, 8, 16, 24, 32, 40, 48, 60, 80, 99),
                default=-1,
                description="-1 offloads every layer the backend can hold",
            ),
            ParameterDimension(
                name="threads",
                kind=DimensionKind.INT,
                minimum=1,
                maximum=64,
                default=8,
                description="CPU threads used for generation and prompt processing",
            ),
            ParameterDimension(
                name="batch",
                kind=DimensionKind.CATEGORICAL,
                choices=(128, 256, 512, 1024, 2048),
                default=2048,
            ),
            ParameterDimension(
                name="ubatch",
                kind=DimensionKind.CATEGORICAL,
                choices=(64, 128, 256, 512),
                default=512,
            ),
            ParameterDimension(
                name="flash_attn",
                kind=DimensionKind.CATEGORICAL,
                choices=("auto", "on", "off"),
                default="auto",
            ),
            ParameterDimension(
                name="cache_type_k",
                kind=DimensionKind.CATEGORICAL,
                choices=("f16", "q8_0", "q4_0"),
                default="f16",
                quality_risk=True,
            ),
            ParameterDimension(
                name="cache_type_v",
                kind=DimensionKind.CATEGORICAL,
                choices=("f16", "q8_0", "q4_0"),
                default="f16",
                conditions=(
                    SearchCondition(parameter="flash_attn", operator=ConditionOperator.EQ, values=("on",)),
                ),
                quality_risk=True,
            ),
        ]
        if "moe" in request.model_architecture.lower() or "expert" in request.model_architecture.lower():
            dimensions.append(
                ParameterDimension(
                    name="n_cpu_moe",
                    kind=DimensionKind.INT,
                    minimum=0,
                    maximum=99,
                    default=0,
                    engine_constraints=("MoE models only",),
                )
            )
        return SearchSpaceSpec(
            engine_id=EngineId.LLAMACPP,
            dimensions=tuple(dimensions),
            fixed_parameters={"ctx_size": request.context_tokens, "reasoning": "off"},
            constraints=("Unknown or unobserved flags are rejected before planning.",),
            max_proposals=256,
            notes=(
                "Conditional dimensions are declared explicitly for Phase 5 TPE integration.",
                "Serving benchmarks disable reasoning consistently for baseline and candidates "
                "so the token budget measures answer generation.",
            ),
        )

    def validate_candidate(
        self, candidate: CandidateSpec, engine: EngineCapabilityManifest
    ) -> tuple[str, ...]:
        errors: list[str] = []
        mapping = {
            "gpu_layers": "--n-gpu-layers",
            "threads": "--threads",
            "batch": "--batch-size",
            "ubatch": "--ubatch-size",
            "reasoning": "--reasoning",
            "flash_attn": "--flash-attn",
            "cache_type_k": "--cache-type-k",
            "cache_type_v": "--cache-type-v",
            "n_cpu_moe": "--n-cpu-moe",
            "ctx_size": "--ctx-size",
            "parallel": "--parallel",
            "kv_unified": "--kv-unified",
            "kv_unified_per_slot": "--kv-unified-per-slot",
            "load_mode": "--load-mode",
            "split_mode": "--split-mode",
            "metrics": "--metrics",
            "prompt_tokens": "--n-prompt",
            "n_gen": "--n-gen",
            "n_depth": "--n-depth",
            "repetitions": "--repetitions",
        }
        for name, value in candidate.parameters.items():
            flag = mapping.get(name)
            if flag is None:
                errors.append(f"unknown llama.cpp parameter {name!r}")
                continue
            capability = engine.descriptor(flag)
            if capability is None:
                errors.append(
                    f"parameter {name!r} requires {flag}, which the installed build does not expose"
                )
                continue
            if capability.support is not SupportLevel.SUPPORTED:
                errors.append(f"parameter {name!r} is not supported by the installed build")
                continue
            errors.extend(validate_capability_value(capability, name, value))
        return tuple(errors)

    # ----------------------------------------------------------------- plans
    def _model_path(self, model: ModelArtifact) -> str:
        if not model.path_map:
            raise ValueError(f"model {model.model_id!r} has no registered path")
        return model.path_map[0]

    def _native_args(self, candidate: CandidateSpec, model: ModelArtifact, repetitions: int) -> list[str]:
        params = candidate.parameters
        prompt_tokens = _as_int(params, "prompt_tokens", min(2048, max(128, int(candidate.context) // 4)))
        gen_tokens = _as_int(params, "n_gen", 256)
        depth = _as_int(params, "n_depth", 0)
        runs = _as_int(params, "repetitions", repetitions)
        args = [
            "-m",
            self._model_path(model),
            "-p",
            str(prompt_tokens),
            "-n",
            str(gen_tokens),
            "-d",
            str(depth),
            "-r",
            str(runs),
            "-o",
            "json",
        ]
        optional = {
            "threads": "-t",
            "batch": "-b",
            "ubatch": "-ub",
            "gpu_layers": "-ngl",
            "n_cpu_moe": "-ncmoe",
            "flash_attn": "-fa",
            "cache_type_k": "-ctk",
            "cache_type_v": "-ctv",
        }
        for name, flag in optional.items():
            if name in params:
                args.extend((flag, str(params[name])))
        return args

    def build_microbench_plan(
        self,
        candidate: CandidateSpec,
        sandbox: SandboxPaths,
        *,
        binary: RegisteredBinary,
        model: ModelArtifact,
        repetitions: int = 3,
    ) -> ExecutionPlan:
        command = CommandSpec(
            executable_id=binary.executable_id,
            executable_sha256=binary.sha256,
            argv=tuple(self._native_args(candidate, model, repetitions)),
            env={"LC_ALL": "C", "LANG": "C", "CUDA_DEVICE_ORDER": "PCI_BUS_ID"},
            cwd=sandbox.work_dir,
            timeout_seconds=3600,
            stdout_schema="llamacpp.llama-bench.json/v1",
            artifacts=(),
        )
        return ExecutionPlan(
            engine_id=EngineId.LLAMACPP,
            candidate_digest=candidate.semantic_key(),
            sandbox=sandbox,
            stages=(ExecutionStage(name="native-microbench", command=command),),
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
        params = candidate.parameters
        args: list[str] = [
            "-m",
            self._model_path(model),
            "--ctx-size",
            str(int(candidate.context)),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
        optional = {
            "threads": "--threads",
            "batch": "--batch-size",
            "ubatch": "--ubatch-size",
            "gpu_layers": "--n-gpu-layers",
            "n_cpu_moe": "--n-cpu-moe",
            "reasoning": "--reasoning",
            "flash_attn": "--flash-attn",
            "cache_type_k": "--cache-type-k",
            "cache_type_v": "--cache-type-v",
            "parallel": "--parallel",
            "load_mode": "--load-mode",
            "split_mode": "--split-mode",
        }
        for name, flag in optional.items():
            if name in params:
                args.extend((flag, str(params[name])))
        if _as_bool(params, "kv_unified", False):
            args.append("--kv-unified")
        if "kv_unified_per_slot" in params:
            args.extend(("--kv-unified-per-slot", str(_as_int(params, "kv_unified_per_slot", 4096))))
        if _as_bool(params, "metrics", False):
            args.append("--metrics")
        command = CommandSpec(
            executable_id=binary.executable_id,
            executable_sha256=binary.sha256,
            argv=tuple(args),
            env={"LC_ALL": "C", "LANG": "C", "CUDA_DEVICE_ORDER": "PCI_BUS_ID"},
            cwd=sandbox.work_dir,
            timeout_seconds=7200,
            readiness=server_readiness("/health", timeout=180),
            stdout_schema="text/plain",
        )
        return ServerExecutionPlan(
            engine_id=EngineId.LLAMACPP,
            candidate_digest=candidate.semantic_key(),
            sandbox=sandbox,
            start=ExecutionStage(name="llama-server", command=command),
            bind_host="127.0.0.1",
            port_range_start=port,
            port_range_end=port,
            health_path="/health",
            metrics_path="/metrics" if _as_bool(params, "metrics", False) else None,
            readiness_timeout_seconds=180,
        )

    # ---------------------------------------------------------------- parsing
    def parse_microbench_evidence(
        self, evidence: RawEvidence, candidate: CandidateSpec
    ) -> MicrobenchObservation:
        document = parse_json_document(evidence.text)
        if not isinstance(document, list) or not document:
            raise ValueError("llama-bench JSON evidence must be a non-empty array")
        rows: list[MicrobenchRow] = []
        for item in document:
            if not isinstance(item, dict):
                raise ValueError("llama-bench JSON rows must be objects")
            test = item.get("test")
            if not isinstance(test, str):
                # Installed build 701 labels rows with token counts rather than
                # a redundant test string. Mixed/empty rows remain ambiguous.
                prompt, generation = item.get("n_prompt"), item.get("n_gen")
                if isinstance(prompt, int) and prompt > 0 and generation == 0:
                    test = f"pp{prompt}"
                elif prompt == 0 and isinstance(generation, int) and generation > 0:
                    test = f"tg{generation}"
                else:
                    raise ValueError("llama-bench row has no unambiguous test identity")
            avg_ts = item.get("avg_ts")
            if avg_ts is not None:
                avg_ts = float(avg_ts)
            samples = tuple(float(value) for value in item.get("samples_ts", []) or [])
            rows.append(
                MicrobenchRow(
                    test=test,
                    n_prompt=int(item.get("n_prompt") or 0),
                    n_gen=int(item.get("n_gen") or 0),
                    n_depth=int(item.get("n_depth") or 0),
                    avg_ts=avg_ts,
                    stddev_ts=float(item["stddev_ts"]) if item.get("stddev_ts") is not None else None,
                    samples_ts=samples,
                    n_threads=item.get("n_threads"),
                    n_gpu_layers=item.get("n_gpu_layers"),
                    type_k=item.get("type_k"),
                    type_v=item.get("type_v"),
                    flash_attn=str(item.get("flash_attn")) if item.get("flash_attn") is not None else None,
                    n_batch=item.get("n_batch"),
                    n_ubatch=item.get("n_ubatch"),
                    n_cpu_moe=item.get("n_cpu_moe"),
                )
            )
        if not any((row.avg_ts or 0) > 0 for row in rows):
            raise ValueError("llama-bench evidence contains no positive throughput measurement")
        first = document[0]
        return MicrobenchObservation(
            engine_id=EngineId.LLAMACPP.value,
            build_commit=first.get("build_commit"),
            build_number=str(first.get("build_number")) if first.get("build_number") is not None else None,
            model_filename=first.get("model_filename"),
            model_type=first.get("model_type"),
            backends=first.get("backends"),
            gpu_info=first.get("gpu_info"),
            rows=tuple(rows),
            raw_sha256=sha256_text(evidence.text),
            warnings=("Build identity comes from the evidence; the worker must verify the executable hash.",),
        )

    def parse_server_evidence(
        self, status: RawEvidence, metrics: RawEvidence | None, candidate: CandidateSpec
    ) -> ServingObservation:
        document = parse_json_document(status.text)
        timings = document.get("timings") if isinstance(document, dict) else None
        context = document.get("context") if isinstance(document, dict) else None
        unavailable: dict[str, str] = {}
        prefill = None
        decode = None
        ttft = None
        total = None
        prompt_n = None
        output_n = None
        if isinstance(timings, dict):
            prefill = timings.get("prompt_per_second")
            decode = timings.get("predicted_per_second")
            prompt_n = timings.get("prompt_n")
            output_n = timings.get("predicted_n")
            if timings.get("prompt_ms") is not None:
                total = float(timings["prompt_ms"]) + float(timings.get("predicted_ms") or 0.0)
            unavailable["time_to_first_token_ms"] = (
                "derived only from client-observed streaming; not present in this endpoint"
            )
        else:
            unavailable["prefill_tokens_per_sec"] = "no per-request timings block in status evidence"
            unavailable["decode_tokens_per_sec"] = "no per-request timings block in status evidence"
            unavailable["time_to_first_token_ms"] = "no per-request timings block in status evidence"
            unavailable["total_latency_ms"] = "no per-request timings block in status evidence"
        effective = None
        if isinstance(document, dict):
            generation = document.get("default_generation_settings")
            effective = document.get("n_ctx")
            if effective is None and isinstance(generation, dict):
                effective = generation.get("n_ctx")
        if effective is None and isinstance(context, dict):
            effective = context.get("native") or context.get("max_positions")
        return ServingObservation(
            engine_id=EngineId.LLAMACPP.value,
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
            unavailable_reasons=unavailable,
            warnings=("llama-server /props is not used to infer per-request throughput.",),
        )

    # --------------------------------------------------------------- recipes
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
        if not hardware.gpus:
            raise ValueError("a deployment recipe requires a GPU hardware snapshot")
        peaks = [
            obs.metrics.gpu_vram_peak_bytes
            for obs in evidence.observations
            if obs.metrics.gpu_vram_peak_bytes
        ]
        if not peaks:
            raise ValueError("a deployment recipe requires measured peak VRAM, not an estimate")
        gpu = hardware.gpus[0]
        args = tuple(self._server_recipe_args(candidate, model))
        recipe_id = stable_id(
            "recipe", candidate.candidate_id, model.artifact_digest, binary.sha256, int(candidate.context)
        )
        return DeploymentRecipe(
            id=recipe_id,
            engine=RecipeEngine(
                id=EngineId.LLAMACPP,
                version=binary.version or "unknown",
                build=binary.build or "unknown",
                executable=binary.path,
                sha256=binary.sha256,
                source_commit=None,
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
            launch=RecipeLaunch(executable=binary.path, argv=args),
            validation=RecipeValidationRefs(
                protocol=evidence.observations[0].protocol,
                experiment_id=evidence.experiment_id,
                metrics_ref=evidence.metrics_ref,
                confidence_ref=evidence.confidence_ref,
                quality_ref=None,
                claim_scope=(f"{int(candidate.context) // 1024}K",),
                validated_at=evidence.validated_at,
            ),
            rollback=RecipeRollback(required_smoke_tests=("ready", "one_token", "profile_identity")),
            notes=("Generated from validated measured evidence only.",),
        )

    def _server_recipe_args(self, candidate: CandidateSpec, model: ModelArtifact) -> list[str]:
        params = candidate.parameters
        args = [
            "-m",
            self._model_path(model),
            "--ctx-size",
            str(int(candidate.context)),
            "--host",
            "127.0.0.1",
        ]
        mapping = {
            "threads": "--threads",
            "batch": "--batch-size",
            "ubatch": "--ubatch-size",
            "gpu_layers": "--n-gpu-layers",
            "n_cpu_moe": "--n-cpu-moe",
            "reasoning": "--reasoning",
            "flash_attn": "--flash-attn",
            "cache_type_k": "--cache-type-k",
            "cache_type_v": "--cache-type-v",
            "parallel": "--parallel",
            "load_mode": "--load-mode",
            "split_mode": "--split-mode",
        }
        for name, flag in mapping.items():
            if name in params:
                args.extend((flag, str(params[name])))
        if _as_bool(params, "kv_unified", False):
            args.append("--kv-unified")
        if "kv_unified_per_slot" in params:
            args.extend(("--kv-unified-per-slot", str(_as_int(params, "kv_unified_per_slot", 4096))))
        if _as_bool(params, "metrics", False):
            args.append("--metrics")
        return args

    def assess_context_feasibility(
        self, candidate: CandidateSpec, engine: EngineCapabilityManifest, hardware: HardwareSnapshot
    ) -> ContextFeasibility:
        return ContextFeasibility(
            context=candidate.context,
            status=FeasibilityOutcome.UNKNOWN,
            reason=(
                "Context fit must be established by a worker-owned llama-server full-context "
                "allocation test; a GGUF header or short llama-bench run is not proof."
            ),
        )


def _objective_for(candidate: CandidateSpec) -> Objective:
    del candidate
    return Objective.BALANCED


# Avoid an unused import warning for WorkloadSuite/ReadinessKind while keeping the
# symbols available to adapter extensions that copy this module.
_ = (WorkloadSuite, ReadinessKind, BenchmarkObservation, ReadinessPredicate)
