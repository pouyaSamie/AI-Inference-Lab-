"""Phase 1 simulated command executor.

Every result carries ``simulated=True``. No subprocess, GPU allocation or live
inference server is used. The controller persists that provenance and refuses
to turn it into a validated recipe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from lab_core.base import utcnow
from lab_core.errors import ValidationFailure
from lab_core.ids import canonical_json, sha256_text

from lab_core import (
    BenchmarkObservation,
    BenchMetrics,
    BenchSample,
    CancelPayload,
    CancelResult,
    ClaimTrialPayload,
    CommandCompletion,
    CommandFailure,
    CommandPayload,
    CommandResult,
    CommandStatus,
    CommandType,
    ContextFeasibility,
    ContextLength,
    EvidenceKind,
    FailureInfo,
    FailureKind,
    FeasibilityOutcome,
    MeasurementStatus,
    ModelArtifact,
    ObservationStatus,
    OOMStage,
    PausePayload,
    PauseResult,
    PreflightPayload,
    PreflightResult,
    PromotePayload,
    PromoteResult,
    QualityGate,
    QualityGateStatus,
    ScanPayload,
    ScanResult,
    TelemetryCoverage,
    TrialResult,
    VerifyRecipePayload,
    VerifyRecipeResult,
    WorkerCommandLease,
    WorkerSnapshot,
)

from .config import WorkerSettings
from .inventory import build_snapshot


def _as_int(parameters: dict[str, Any], key: str, default: int) -> int:
    value = parameters.get(key)
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else default


def _as_str(parameters: dict[str, Any], key: str, default: str) -> str:
    value = parameters.get(key)
    return str(value) if isinstance(value, str) else default


def _unit(seed: str) -> float:
    return int(sha256_text(seed)[:8], 16) / 0xFFFFFFFF


@dataclass
class SimulatedExecutor:
    settings: WorkerSettings
    revision: int = 1
    snapshot: WorkerSnapshot = field(init=False)

    def __post_init__(self) -> None:
        self.snapshot = build_snapshot(self.settings, max(1, self.revision))

    # --------------------------------------------------------------- command
    def execute(self, lease: WorkerCommandLease) -> CommandCompletion:
        command = lease.command
        try:
            result = self.dispatch(command.command_type, command.payload)
            return CommandCompletion(
                worker_id=self.settings.worker_id,
                lease_token=lease.lease_token,
                lease_generation=lease.lease_generation,
                outcome=CommandStatus.COMPLETED,
                result=result,
            )
        except Exception as exc:
            kind = FailureKind.SIMULATION_ERROR
            if isinstance(exc, ValidationFailure):
                kind = FailureKind.INVALID_METRICS
            return CommandCompletion(
                worker_id=self.settings.worker_id,
                lease_token=lease.lease_token,
                lease_generation=lease.lease_generation,
                outcome=CommandStatus.FAILED,
                failure=CommandFailure(
                    kind=kind,
                    message=f"{type(exc).__name__}: {exc}"[:2000],
                    retryable=False,
                ),
            )

    def dispatch(self, command_type: CommandType, payload: CommandPayload) -> CommandResult:
        if command_type is CommandType.SCAN:
            return self._scan(cast(ScanPayload, payload))
        if command_type is CommandType.PREFLIGHT:
            return self._preflight(cast(PreflightPayload, payload))
        if command_type is CommandType.CLAIM_TRIAL:
            return self._claim(cast(ClaimTrialPayload, payload))
        if command_type is CommandType.PAUSE:
            return self._pause(cast(PausePayload, payload))
        if command_type is CommandType.CANCEL:
            return self._cancel(cast(CancelPayload, payload))
        if command_type is CommandType.VERIFY_RECIPE:
            return self._verify(cast(VerifyRecipePayload, payload))
        if command_type is CommandType.PROMOTE:
            return self._promote(cast(PromotePayload, payload))
        raise ValidationFailure(f"unsupported command type {command_type!r}")

    # ------------------------------------------------------------------ scan
    def _scan(self, payload: ScanPayload) -> ScanResult:
        self.snapshot = build_snapshot(self.settings, self.snapshot.revision + 1)
        return ScanResult(
            snapshot=self.snapshot,
            warnings=("SIMULATED_INVENTORY", "NO_LIVE_PROBE_PERFORMED"),
        )

    # --------------------------------------------------------------- preflight
    def _preflight(self, payload: PreflightPayload) -> PreflightResult:
        engine = self.snapshot.engine(payload.engine.engine_id.value)
        model = self.snapshot.model(payload.model.model_id)
        feasibility: list[ContextFeasibility] = []
        if engine is None:
            return PreflightResult(
                experiment_id=payload.experiment_id,
                passed=False,
                feasibility=tuple(
                    ContextFeasibility(
                        context=context,
                        status=FeasibilityOutcome.UNSUPPORTED,
                        reason="engine is absent from the simulated worker inventory",
                    )
                    for context in payload.contexts
                ),
                engine_sha256=payload.engine.executable_sha256,
                model_digest=payload.model.artifact_digest,
                snapshot_revision=self.snapshot.revision,
                message="engine is absent from the simulated worker inventory",
                failure_kind=FailureKind.UNSUPPORTED_MODEL,
            )
        if engine.engine.executable_sha256 != payload.engine.executable_sha256:
            return PreflightResult(
                experiment_id=payload.experiment_id,
                passed=False,
                feasibility=tuple(
                    ContextFeasibility(
                        context=context,
                        status=FeasibilityOutcome.INCONCLUSIVE,
                        reason="engine identity changed; refresh inventory",
                    )
                    for context in payload.contexts
                ),
                engine_sha256=payload.engine.executable_sha256,
                model_digest=payload.model.artifact_digest,
                snapshot_revision=self.snapshot.revision,
                message="engine identity mismatch",
                failure_kind=FailureKind.UNSUPPORTED_MODEL,
            )
        if model is None or model.artifact_digest != payload.model.artifact_digest:
            return PreflightResult(
                experiment_id=payload.experiment_id,
                passed=False,
                feasibility=tuple(
                    ContextFeasibility(
                        context=context,
                        status=FeasibilityOutcome.UNSUPPORTED,
                        reason="model is absent or has changed",
                    )
                    for context in payload.contexts
                ),
                engine_sha256=payload.engine.executable_sha256,
                model_digest=payload.model.artifact_digest,
                snapshot_revision=self.snapshot.revision,
                message="model identity mismatch",
                failure_kind=FailureKind.UNSUPPORTED_MODEL,
            )

        for context in payload.contexts:
            feasibility.append(self._feasibility(model, context))
        passed = all(item.status is FeasibilityOutcome.FEASIBLE for item in feasibility)
        failed = next((item for item in feasibility if item.status is not FeasibilityOutcome.FEASIBLE), None)
        return PreflightResult(
            experiment_id=payload.experiment_id,
            passed=passed,
            feasibility=tuple(feasibility),
            engine_sha256=engine.engine.executable_sha256,
            model_digest=model.artifact_digest,
            snapshot_revision=self.snapshot.revision,
            message=(
                "simulated full-context preflight passed for every requested context"
                if passed
                else (failed.reason if failed else "preflight failed")
            ),
            failure_kind=None
            if passed
            else (
                FailureKind.INSUFFICIENT_VRAM
                if failed and failed.status is FeasibilityOutcome.RESOURCE_INFEASIBLE
                else FailureKind.INVALID_METRICS
            ),
        )

    def _feasibility(self, model: ModelArtifact, context: ContextLength) -> ContextFeasibility:
        context_int = int(context)
        estimate = 3_800_000_000 + context_int * 75_000
        if context_int > (model.metadata_context_tokens or 0):
            return ContextFeasibility(
                context=context,
                status=FeasibilityOutcome.RESOURCE_INFEASIBLE,
                estimated_vram_bytes=estimate,
                reason=(
                    f"requested context {context_int} exceeds the model metadata limit "
                    f"{model.metadata_context_tokens}"
                ),
                evidence=("SIMULATED_FULL_CONTEXT_CHECK",),
                requires_full_context_proof=True,
            )
        if context_int > 32768:
            return ContextFeasibility(
                context=context,
                status=FeasibilityOutcome.RESOURCE_INFEASIBLE,
                estimated_vram_bytes=estimate,
                reason="simulated 12 GiB GPU cannot prove this context fit",
                evidence=("SIMULATED_VRAM_ESTIMATE",),
                requires_full_context_proof=True,
            )
        return ContextFeasibility(
            context=context,
            status=FeasibilityOutcome.FEASIBLE,
            estimated_vram_bytes=estimate,
            reason="simulated full-context allocation proof",
            evidence=("SIMULATED_FULL_CONTEXT_CHECK", "effective_context==configured_context"),
            requires_full_context_proof=True,
        )

    # ---------------------------------------------------------------- trial
    def _claim(self, payload: ClaimTrialPayload) -> TrialResult:
        if not payload.simulation_only:
            raise ValidationFailure(
                "Phase 1 worker only implements explicitly simulated trials; real execution is Phase 2"
            )
        observation = self._observation(payload)
        return TrialResult(observation=observation)

    def _observation(self, payload: ClaimTrialPayload) -> BenchmarkObservation:
        context = int(payload.context)
        parameters = payload.parameters
        gpu_layers = _as_int(parameters, "gpu_layers", -1)
        if gpu_layers == 0 and context >= 8192:
            return BenchmarkObservation(
                experiment_id=payload.experiment_id,
                study_id=payload.study_id,
                candidate_id=payload.candidate_id,
                trial_number=payload.trial_number,
                attempt=0,
                worker_id=self.settings.worker_id,
                engine_id=payload.engine.engine_id.value,
                engine_sha256=payload.engine.executable_sha256,
                model_digest=payload.model.artifact_digest,
                workload_digest=payload.workload_digest,
                context=payload.context,
                evidence_kind=EvidenceKind.SIMULATED,
                measurement_status=MeasurementStatus.INFEASIBLE,
                status=ObservationStatus.RESOURCE_INFEASIBLE,
                configured_context=context,
                effective_context=None,
                input_tokens=min(context, 2048),
                output_tokens=256,
                metrics=BenchMetrics(
                    gpu_vram_peak_bytes=12 * 1024**3,
                    cpu_rss_peak_bytes=2 * 1024**3,
                    unavailable_reasons={"throughput": "simulated CUDA OOM"},
                ),
                failure=FailureInfo(
                    kind=FailureKind.INSUFFICIENT_VRAM,
                    stage=OOMStage.MODEL_LOAD,
                    message="simulated full-GPU offload at this context exhausted 12 GiB VRAM",
                    retryable=False,
                ),
                simulated=True,
                observed_at=utcnow(),
                notes=("SIMULATED failure; not a real engine observation.",),
            )

        threads = _as_int(parameters, "threads", 8)
        batch = _as_int(parameters, "batch", 2048)
        ubatch = _as_int(parameters, "ubatch", 512)
        flash = _as_str(parameters, "flash_attn", "auto")
        cache_k = _as_str(parameters, "cache_type_k", "f16")
        cache_v = _as_str(parameters, "cache_type_v", "f16")
        jitter = 0.95 + 0.10 * _unit(canonical_json(parameters))
        context_factor = max(0.45, 1.0 - (context / 131072.0) * 0.55)
        layer_factor = 1.25 if gpu_layers < 0 or gpu_layers >= 24 else max(0.20, 0.55 + gpu_layers / 60.0)
        thread_factor = 0.90 + 0.20 * (min(max(threads, 1), 16) / 16.0)
        batch_factor = 0.85 + 0.15 * (min(max(batch, 128), 2048) / 2048.0)
        ubatch_factor = 0.90 + 0.10 * (min(max(ubatch, 64), 512) / 512.0)
        flash_factor = {"on": 1.05, "auto": 1.0, "off": 0.94}.get(flash, 1.0)
        cache_factor = 1.0
        cache_factor *= {"q4_0": 1.12, "q8_0": 1.06}.get(cache_k, 1.0)
        cache_factor *= {"q4_0": 1.12, "q8_0": 1.06}.get(cache_v, 1.0)

        prefill = 900.0 * context_factor * layer_factor * batch_factor * ubatch_factor * flash_factor * jitter
        decode = 95.0 * context_factor * layer_factor * thread_factor * cache_factor * flash_factor * jitter
        input_tokens = min(context, 2048)
        output_tokens = 256
        repetitions = max(1, payload.workload.repetitions if payload.workload else 1)
        samples: list[BenchSample] = []
        for index in range(repetitions):
            # A deterministic, symmetric spread keeps the simulated median
            # stable while still exercising paired-bootstrap paths.
            spread = (index - (repetitions - 1) / 2.0) * 0.008
            sample_prefill = prefill * (1.0 + spread)
            sample_decode = decode * (1.0 - spread)
            sample_ttft = 20.0 + (input_tokens / max(sample_prefill, 1.0)) * 1000.0
            sample_total = sample_ttft + (output_tokens / max(sample_decode, 1.0)) * 1000.0
            samples.append(
                BenchSample(
                    prefill_tokens_per_sec=round(sample_prefill, 3),
                    decode_tokens_per_sec=round(sample_decode, 3),
                    time_to_first_token_ms=round(sample_ttft, 3),
                    total_latency_ms=round(sample_total, 3),
                )
            )
        ttft_ms = samples[0].time_to_first_token_ms or 0.0
        total_ms = samples[0].total_latency_ms or 0.0
        vram = 3_800_000_000 + context * 75_000
        quality_gates: tuple[QualityGate, ...] = (
            QualityGate(
                name="simulated_schema",
                status=QualityGateStatus.PASSED,
                score=1.0,
                threshold=1.0,
                details="contract-shape gate only; this is not a quality measurement",
            ),
        )
        if cache_k in {"q4_0"} or cache_v in {"q4_0"}:
            quality_gates = (
                *quality_gates,
                QualityGate(
                    name="cache_quantization_quality",
                    status=QualityGateStatus.INCONCLUSIVE,
                    details="simulated run cannot establish text quality",
                ),
            )
        return BenchmarkObservation(
            experiment_id=payload.experiment_id,
            study_id=payload.study_id,
            candidate_id=payload.candidate_id,
            trial_number=payload.trial_number,
            attempt=0,
            worker_id=self.settings.worker_id,
            engine_id=payload.engine.engine_id.value,
            engine_sha256=payload.engine.executable_sha256,
            model_digest=payload.model.artifact_digest,
            workload_digest=payload.workload_digest,
            context=payload.context,
            evidence_kind=EvidenceKind.SIMULATED,
            measurement_status=MeasurementStatus.SIMULATED,
            status=ObservationStatus.COMPLETED,
            metrics=BenchMetrics(
                prefill_tokens_per_sec=round(prefill, 3),
                decode_tokens_per_sec=round(decode, 3),
                time_to_first_token_ms=round(ttft_ms, 3),
                total_latency_ms=round(total_ms, 3),
                cold_start_ms=1500.0,
                server_ready_ms=2500.0,
                model_load_sec=2.5,
                gpu_vram_peak_bytes=vram,
                cpu_rss_peak_bytes=2_400_000_000,
                system_ram_available_min_bytes=40 * 1024**3,
                gpu_utilization=0.88,
                gpu_memory_utilization=0.55,
                gpu_temperature_max_c=61.0,
                gpu_power_average_w=180.0,
                gpu_sm_clock_mhz=1900,
                gpu_mem_clock_mhz=7500,
                cache_hit=False,
            ),
            configured_context=context,
            effective_context=context,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            repetitions=len(samples),
            samples=tuple(samples),
            dispersion={"decode_tokens_per_sec": 0.02, "prefill_tokens_per_sec": 0.02},
            telemetry=TelemetryCoverage(
                source="simulated",
                sample_interval_ms=250,
                samples=8,
                expected_samples=8,
                coverage=1.0,
                notes=("SIMULATED telemetry; no NVML sampling occurred.",),
            ),
            quality_gates=quality_gates,
            simulated=True,
            observed_at=utcnow(),
            notes=("SIMULATED Phase 1 observation; not production evidence.",),
        )

    # ------------------------------------------------------------- lifecycle
    def _pause(self, payload: PausePayload) -> PauseResult:
        return PauseResult(
            experiment_id=payload.experiment_id,
            accepted=True,
            paused_at_stage="screening",
            message="simulated worker accepted pause; no process is running",
        )

    def _cancel(self, payload: CancelPayload) -> CancelResult:
        return CancelResult(
            experiment_id=payload.experiment_id,
            accepted=True,
            terminated_owned_pids=(),
            message="simulated worker accepted cancel; no process is running",
        )

    def _verify(self, payload: VerifyRecipePayload) -> VerifyRecipeResult:
        engine = self.snapshot.engine(self.settings.engine_id)
        mismatches: list[str] = []
        if engine is None or engine.engine.executable_sha256 != payload.expected_engine_sha256:
            mismatches.append("engine_sha256")
        model = self.snapshot.model(self.settings.model_id)
        if model is None or model.artifact_digest != payload.expected_model_digest:
            mismatches.append("model_digest")
        return VerifyRecipeResult(
            recipe_id=payload.recipe_id,
            verified=not mismatches,
            engine_sha256=engine.engine.executable_sha256 if engine else None,
            model_digest=model.artifact_digest if model else None,
            mismatches=tuple(mismatches),
            message=(
                "simulated recipe identity verification passed"
                if not mismatches
                else "simulated recipe identity verification failed"
            ),
        )

    def _promote(self, payload: PromotePayload) -> PromoteResult:
        return PromoteResult(
            recipe_id=payload.recipe_id,
            promoted=not payload.dry_run,
            dry_run=payload.dry_run,
            slot=payload.target_slot,
            message=(
                "simulated promotion dry-run; no files were written"
                if payload.dry_run
                else "simulated promotion recorded; no live slot was changed"
            ),
        )
