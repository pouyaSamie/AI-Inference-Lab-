"""Real Linux worker executor for the durable command protocol.

The executor owns all side effects: process spawning, GPU leases, sandboxes,
journals and measurement parsing. Pure adapters only translate typed plans.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from threading import Event
from typing import Any, cast

from lab_core.ids import sha256_hex

from lab_core import (
    BenchmarkObservation,
    BenchMetrics,
    CancelPayload,
    CancelResult,
    CandidateSpec,
    ClaimTrialPayload,
    CommandCompletion,
    CommandFailure,
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
    RawEvidence,
    RawEvidenceRef,
    ScanPayload,
    ScanResult,
    TelemetryCoverage,
    TrialResult,
    VerifyRecipePayload,
    VerifyRecipeResult,
    WorkerCommandLease,
)

from .bench import derive_serving_metrics, effective_context, run_serving_workload
from .config import WorkerSettings
from .discovery import DiscoveryResult, discover_snapshot
from .engines import EngineBundle, discover_engines, sha256_file
from .gpu import GpuLease, GpuLeaseError, GpuLeaseManager
from .hardware import TelemetrySummary, gpu_preflight
from .journal import WorkerJournal
from .runner import ProcessRunner, RunResult, ServerProcess, allocate_loopback_port
from .sandbox import create_sandbox

logger = logging.getLogger(__name__)


class RealExecutionError(RuntimeError):
    pass


def _failure_kind(text: str, *, cancelled: bool, timed_out: bool) -> tuple[FailureKind, OOMStage]:
    lower = text.lower()
    if cancelled:
        return FailureKind.CANCELLED, OOMStage.UNKNOWN
    if timed_out or "timed out" in lower:
        return FailureKind.TIMEOUT, OOMStage.UNKNOWN
    if any(
        marker in lower
        for marker in (
            "out of memory",
            "outofmemory",
            "cuda error: out of memory",
            "cudaMalloc failed".lower(),
            "insufficient memory",
            "failed to allocate",
        )
    ):
        if "kv" in lower or "context" in lower:
            return FailureKind.INSUFFICIENT_VRAM, OOMStage.KV_ALLOCATION
        if "load" in lower or "model" in lower:
            return FailureKind.INSUFFICIENT_VRAM, OOMStage.MODEL_LOAD
        return FailureKind.OOM, OOMStage.UNKNOWN
    if "unsupported" in lower or "unknown argument" in lower or "invalid argument" in lower:
        return FailureKind.UNSUPPORTED_FLAG, OOMStage.UNKNOWN
    if "failed to load" in lower or "error loading model" in lower:
        return FailureKind.MODEL_LOAD_FAILURE, OOMStage.MODEL_LOAD
    if "health" in lower or "did not become ready" in lower:
        return FailureKind.SERVER_NOT_READY, OOMStage.UNKNOWN
    return FailureKind.UNKNOWN, OOMStage.UNKNOWN


def _write_generated_files(plan: Any, sandbox_root: Path) -> None:
    for generated in getattr(plan, "generated_files", ()):
        target = sandbox_root / generated.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generated.content, encoding="utf-8")
        actual = sha256_file(target)
        if generated.sha256 and actual != generated.sha256:
            raise RealExecutionError(f"generated file digest mismatch: {generated.relative_path}")


def _combine_evidence(*groups: tuple[RawEvidenceRef, ...]) -> tuple[RawEvidenceRef, ...]:
    seen: dict[str, RawEvidenceRef] = {}
    for group in groups:
        for item in group:
            seen.setdefault(item.path, item)
    return tuple(seen.values())


class RealExecutor:
    def __init__(
        self,
        settings: WorkerSettings,
        *,
        client: Any | None = None,
        journal: WorkerJournal | None = None,
        leases: GpuLeaseManager | None = None,
        runner: ProcessRunner | None = None,
        discovery: DiscoveryResult | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.journal = journal or WorkerJournal(settings.resolved_journal_root, settings.worker_id)
        self.leases = leases or GpuLeaseManager(settings.resolved_lease_root, settings.worker_id)
        self.discovery = discovery
        self._engines: tuple[EngineBundle, ...] = discovery.engines if discovery else ()
        self._snapshot_revision = discovery.snapshot.revision if discovery else 0
        self._registry: dict[str, Any] = {}
        self._reindex()
        self.runner = runner or ProcessRunner(
            settings,
            binaries=self._registry,
            journal=self.journal,
        )
        self._active: dict[str, Event] = {}
        self._lock = threading.Lock()
        self._last_scan: DiscoveryResult | None = discovery
        self._current_command: str | None = None

    # --------------------------------------------------------------- plumbing
    def _reindex(self) -> None:
        registry: dict[str, Any] = {}
        for bundle in self._engines:
            registry.update(bundle.binaries)
        self._registry = registry
        if getattr(self, "runner", None) is not None:
            self.runner.binaries = registry

    def current_snapshot(self) -> Any | None:
        return self._last_scan.snapshot if self._last_scan else None

    def _bundle(self, engine_id: str) -> EngineBundle:
        bundle = next((item for item in self._engines if item.engine_id.value == engine_id), None)
        if bundle is None:
            bundles, warnings = discover_engines(self.settings)
            self._engines = bundles
            self._reindex()
            bundle = next((item for item in bundles if item.engine_id.value == engine_id), None)
            if bundle is None:
                raise RealExecutionError(
                    f"engine {engine_id!r} is not available on this worker: {'; '.join(warnings)}"
                )
        return bundle

    def _model(self, payload: Any) -> ModelArtifact:
        model = payload.model
        if not isinstance(model, ModelArtifact):
            raise RealExecutionError("command payload has no model artifact")
        return model

    def _renew_callback(self, lease: WorkerCommandLease) -> Any:
        def _tick() -> None:
            if self.client is None:
                return
            try:
                self.client.renew(
                    command_id=lease.command.command_id,
                    lease_token=lease.lease_token,
                    lease_generation=lease.lease_generation,
                    extend_seconds=max(60, int(self.settings.lease_renew_seconds * 2)),
                )
            except Exception:
                logger.warning("command lease renewal failed", exc_info=True)

        return _tick

    # --------------------------------------------------------------- dispatch
    def execute(self, lease: WorkerCommandLease) -> CommandCompletion:
        command = lease.command
        self.journal.command_started(
            command_id=command.command_id,
            command_type=command.command_type.value,
            lease_token=lease.lease_token,
            lease_generation=lease.lease_generation,
            experiment_id=getattr(command.payload, "experiment_id", None),
        )
        with self._lock:
            self._current_command = command.command_id
        outcome = CommandStatus.FAILED
        result: CommandResult | None = None
        failure: CommandFailure | None = None
        try:
            if command.command_type is CommandType.SCAN:
                result = self._scan(cast(ScanPayload, command.payload))
            elif command.command_type is CommandType.PREFLIGHT:
                result = self._preflight(cast(PreflightPayload, command.payload))
            elif command.command_type is CommandType.CLAIM_TRIAL:
                result = self._trial(cast(ClaimTrialPayload, command.payload), lease)
            elif command.command_type is CommandType.PAUSE:
                result = self._pause(cast(PausePayload, command.payload))
            elif command.command_type is CommandType.CANCEL:
                result = self._cancel(cast(CancelPayload, command.payload))
            elif command.command_type is CommandType.VERIFY_RECIPE:
                result = self._verify(cast(VerifyRecipePayload, command.payload))
            elif command.command_type is CommandType.PROMOTE:
                result = self._promote(cast(PromotePayload, command.payload))
            else:
                raise RealExecutionError(f"unsupported command type {command.command_type}")
            outcome = CommandStatus.COMPLETED
        except GpuLeaseError as exc:
            failure = CommandFailure(
                kind=FailureKind.LEASE_CONFLICT,
                message=str(exc)[:2000],
                retryable=True,
                details={"phase": "gpu_lease"},
            )
        except Exception as exc:
            logger.exception("real command failed", extra={"command_id": command.command_id})
            failure = CommandFailure(
                kind=FailureKind.UNKNOWN,
                message=f"{type(exc).__name__}: {str(exc)[:2000]}",
                retryable=False,
                details={"command_id": command.command_id},
            )
        finally:
            with self._lock:
                self._current_command = None
            self.journal.command_finished(command_id=command.command_id, outcome=outcome.value)
        if outcome is CommandStatus.COMPLETED and result is not None:
            return CommandCompletion(
                worker_id=self.settings.worker_id,
                lease_token=lease.lease_token,
                lease_generation=lease.lease_generation,
                outcome=outcome,
                result=result,
            )
        return CommandCompletion(
            worker_id=self.settings.worker_id,
            lease_token=lease.lease_token,
            lease_generation=lease.lease_generation,
            outcome=outcome,
            failure=failure or CommandFailure(kind=FailureKind.UNKNOWN, message="command produced no result"),
        )

    # ------------------------------------------------------------------- scan
    def _scan(self, payload: ScanPayload) -> ScanResult:
        allowed = self.settings.resolved_model_roots
        requested: list[Path] = []
        for raw in payload.roots or tuple(str(item) for item in allowed):
            candidate = Path(raw).expanduser().resolve(strict=False)
            if any(_is_under(candidate, root) for root in allowed):
                requested.append(candidate)
        warnings: list[str] = []
        if not requested:
            warnings.append("SCAN_ROOTS_OUTSIDE_CONFIGURED_MODEL_ROOTS")
            requested = list(allowed)
        revision = max(self._snapshot_revision + 1, 1)
        discovery = discover_snapshot(
            self.settings,
            revision=revision,
            roots=tuple(dict.fromkeys(requested)),
            active_leases=self.leases.active(),
            owned_pids=(),
            include_engines=payload.include_engines,
            include_models=payload.include_models,
            include_hardware=payload.include_hardware,
            hash_models=payload.hash_models,
        )
        self._last_scan = discovery
        self._snapshot_revision = discovery.snapshot.revision
        self._engines = discovery.engines
        self._reindex()
        warnings.extend(discovery.warnings)
        return ScanResult(snapshot=discovery.snapshot, warnings=tuple(dict.fromkeys(warnings)))

    # -------------------------------------------------------------- preflight
    def _preflight(self, payload: PreflightPayload) -> PreflightResult:
        model = self._model(payload)
        bundle = self._bundle(payload.engine.engine_id.value)
        if bundle.manifest.engine.executable_sha256 != payload.engine.executable_sha256:
            return PreflightResult(
                experiment_id=payload.experiment_id,
                passed=False,
                engine_sha256=bundle.manifest.engine.executable_sha256,
                model_digest=model.artifact_digest,
                snapshot_revision=self._snapshot_revision,
                snapshot=self._last_scan.snapshot if self._last_scan else None,
                message="installed engine digest changed since the plan; run SCAN again",
                failure_kind=FailureKind.UNSUPPORTED_MODEL,
            )
        if not model.hashes_complete():
            return PreflightResult(
                experiment_id=payload.experiment_id,
                passed=False,
                engine_sha256=bundle.manifest.engine.executable_sha256,
                model_digest=model.artifact_digest,
                snapshot_revision=self._snapshot_revision,
                snapshot=self._last_scan.snapshot if self._last_scan else None,
                message="model artifact hashes are incomplete; run SCAN with hashing enabled",
                failure_kind=FailureKind.UNSUPPORTED_MODEL,
            )
        contexts = tuple(payload.contexts)
        if not contexts:
            return PreflightResult(
                experiment_id=payload.experiment_id,
                passed=False,
                engine_sha256=bundle.manifest.engine.executable_sha256,
                model_digest=model.artifact_digest,
                snapshot_revision=self._snapshot_revision,
                snapshot=self._last_scan.snapshot if self._last_scan else None,
                message="no contexts were requested",
                failure_kind=FailureKind.UNSUPPORTED_FLAG,
            )
        supported = tuple(
            context
            for context in contexts
            if model.metadata_context_tokens is None or int(context) <= model.metadata_context_tokens
        )
        proof: ContextFeasibility | None = None
        probe_context: ContextLength | None = None
        if supported and bundle.engine_id.value == "llamacpp" and payload.full_context_check:
            probe_context = max(supported, key=int)
            proof = self._preflight_allocation(payload, bundle, model, probe_context)
        feasibility: list[ContextFeasibility] = []
        for context in contexts:
            if context not in ContextLength:
                feasibility.append(
                    ContextFeasibility(
                        context=context,
                        status=FeasibilityOutcome.UNSUPPORTED,
                        reason="context is outside the supported union",
                    )
                )
                continue
            if model.metadata_context_tokens is not None and int(context) > model.metadata_context_tokens:
                feasibility.append(
                    ContextFeasibility(
                        context=context,
                        status=FeasibilityOutcome.UNSUPPORTED,
                        reason=(
                            f"model metadata declares a {model.metadata_context_tokens}-token training "
                            f"context; {int(context)} was not claimed as feasible"
                        ),
                    )
                )
                continue
            if bundle.engine_id.value != "llamacpp":
                feasibility.append(
                    ContextFeasibility(
                        context=context,
                        status=FeasibilityOutcome.INCONCLUSIVE,
                        reason=(
                            "the installed Strata build has no calibration command; a full-context "
                            "allocation proof will be added with the Phase 4 serving harness"
                        ),
                        requires_full_context_proof=True,
                    )
                )
                continue
            if not payload.full_context_check:
                feasibility.append(
                    ContextFeasibility(
                        context=context,
                        status=FeasibilityOutcome.INCONCLUSIVE,
                        reason="full-context allocation check was not requested",
                        requires_full_context_proof=True,
                    )
                )
                continue
            if proof is None or probe_context is None:
                feasibility.append(
                    ContextFeasibility(
                        context=context,
                        status=FeasibilityOutcome.INCONCLUSIVE,
                        reason="no usable full-context allocation proof was produced",
                        requires_full_context_proof=True,
                    )
                )
                continue
            if proof.status is FeasibilityOutcome.FEASIBLE:
                feasibility.append(
                    ContextFeasibility(
                        context=context,
                        status=FeasibilityOutcome.FEASIBLE,
                        estimated_vram_bytes=None,
                        reason=(
                            f"covered by the full-context CPU allocation proof at {int(probe_context)}; "
                            "GPU fit is measured by each candidate trial, not inferred here"
                        ),
                        evidence=(*proof.evidence, f"proof_context={int(probe_context)}"),
                        requires_full_context_proof=True,
                    )
                )
            else:
                feasibility.append(
                    proof.model_copy(
                        update={
                            "context": context,
                            "reason": (
                                f"maximum supported context proof at {int(probe_context)}: "
                                f"{proof.reason or proof.status.value}"
                            ),
                        }
                    )
                )
        passed = bool(feasibility) and all(item.status is FeasibilityOutcome.FEASIBLE for item in feasibility)
        return PreflightResult(
            experiment_id=payload.experiment_id,
            passed=passed,
            feasibility=tuple(feasibility),
            engine_sha256=bundle.manifest.engine.executable_sha256,
            model_digest=model.artifact_digest,
            snapshot_revision=self._snapshot_revision,
            snapshot=self._last_scan.snapshot if self._last_scan else None,
            message=(
                "full-context CPU allocation proof completed"
                if passed
                else "at least one selected context is not proven feasible"
            ),
        )

    def _preflight_allocation(
        self,
        payload: PreflightPayload,
        bundle: EngineBundle,
        model: ModelArtifact,
        context: ContextLength,
    ) -> ContextFeasibility:
        if bundle.server_binary is None or not model.path_map:
            return ContextFeasibility(
                context=context,
                status=FeasibilityOutcome.INCONCLUSIVE,
                reason="no usable llama-server binary or model path was observed",
            )
        command_id = f"preflight-{payload.experiment_id}-{int(context)}"
        sandbox = create_sandbox(self.settings, command_id)
        port = allocate_loopback_port()
        command = bundle.adapter.build_server_plan(
            CandidateSpec(
                study_id=f"preflight-{payload.experiment_id}",
                experiment_id=payload.experiment_id,
                trial_number=0,
                engine_id=bundle.engine_id.value,
                engine_sha256=bundle.manifest.engine.executable_sha256,
                model_digest=model.artifact_digest,
                worker_id=self.settings.worker_id,
                context=context,
                parameters={"gpu_layers": 0},
                workload_digest=sha256_hex({"preflight": payload.spec_digest}),
            ),
            sandbox,
            binary=bundle.server_binary,
            model=model,
            port=port,
        ).start.command
        server, result = self.runner.start_server(
            command_id=command_id,
            stage="preflight-context",
            command=command,
            sandbox=sandbox,
            port=port,
        )
        try:
            if server is None:
                kind, _stage = _failure_kind(
                    result.stdout_text() + "\n" + result.stderr_text(),
                    cancelled=result.cancelled,
                    timed_out=result.timed_out,
                )
                if kind in {FailureKind.INSUFFICIENT_VRAM, FailureKind.OOM}:
                    return ContextFeasibility(
                        context=context,
                        status=FeasibilityOutcome.RESOURCE_INFEASIBLE,
                        reason=f"full-context CPU allocation failed ({kind.value})",
                        evidence=(f"process_exit={result.exit_code}",),
                    )
                return ContextFeasibility(
                    context=context,
                    status=FeasibilityOutcome.INCONCLUSIVE,
                    reason=result.error or f"context allocation probe failed ({kind.value})",
                    evidence=(f"process_exit={result.exit_code}",),
                )
            effective, document = effective_context(port)
            if effective is None:
                return ContextFeasibility(
                    context=context,
                    status=FeasibilityOutcome.INCONCLUSIVE,
                    reason="server started but did not report an effective context; no proof was invented",
                )
            if effective < int(context):
                return ContextFeasibility(
                    context=context,
                    status=FeasibilityOutcome.RESOURCE_INFEASIBLE,
                    reason=f"server effective context {effective} is below configured {int(context)}",
                    evidence=(f"effective_context={effective}",),
                )
            return ContextFeasibility(
                context=context,
                status=FeasibilityOutcome.FEASIBLE,
                estimated_vram_bytes=None,
                reason=(
                    "full-context CPU allocation proof passed at this context; "
                    "GPU fit is measured by each candidate trial, not inferred here"
                ),
                evidence=(
                    f"effective_context={effective}",
                    "allocation_gpu_layers=0",
                    f"status_digest={sha256_hex(document)}",
                ),
                requires_full_context_proof=True,
            )
        finally:
            if server is not None:
                server.stop()

    # ------------------------------------------------------------------- trial
    def _trial(self, payload: ClaimTrialPayload, lease: WorkerCommandLease) -> TrialResult:
        if payload.simulation_only:
            raise RealExecutionError("simulated trial routed to the real worker")
        model = self._model(payload)
        bundle = self._bundle(payload.engine.engine_id.value)
        if bundle.manifest.engine.executable_sha256 != payload.engine.executable_sha256:
            raise RealExecutionError("engine digest changed since the plan; run SCAN again")
        if not model.hashes_complete():
            return TrialResult(
                observation=self._failed_observation(
                    payload,
                    candidate_id=payload.candidate_id,
                    failure=FailureInfo(
                        kind=FailureKind.UNSUPPORTED_MODEL,
                        message="model artifact hashes are incomplete; run SCAN with hashing enabled",
                    ),
                    evidence_kind=EvidenceKind.NATIVE_MICROBENCH,
                )
            )
        try:
            candidate = CandidateSpec(
                study_id=payload.study_id,
                experiment_id=payload.experiment_id,
                trial_number=int(payload.trial_number),
                engine_id=payload.engine.engine_id.value,
                engine_sha256=payload.engine.executable_sha256,
                model_digest=model.artifact_digest,
                worker_id=self.settings.worker_id,
                context=payload.context,
                parameters=payload.parameters,
                parameter_digest=payload.parameter_digest,
                workload_digest=payload.workload_digest,
            )
        except Exception as exc:
            return TrialResult(
                observation=self._failed_observation(
                    payload,
                    candidate_id=payload.candidate_id,
                    failure=FailureInfo(
                        kind=FailureKind.UNSUPPORTED_FLAG,
                        message=f"candidate validation failed: {exc}",
                    ),
                    evidence_kind=EvidenceKind.NATIVE_MICROBENCH,
                )
            )
        errors = bundle.adapter.validate_candidate(candidate, bundle.manifest)
        if errors:
            return TrialResult(
                observation=self._failed_observation(
                    payload,
                    candidate_id=candidate.candidate_id,
                    failure=FailureInfo(
                        kind=FailureKind.UNSUPPORTED_FLAG,
                        message="; ".join(errors)[:2000],
                    ),
                    evidence_kind=EvidenceKind.NATIVE_MICROBENCH,
                )
            )
        compatibility = bundle.adapter.check_compatibility(
            model,
            bundle.manifest,
            self._last_scan.snapshot.hardware if self._last_scan else self._hardware_for_compat(),
        )
        if not compatibility.compatible:
            return TrialResult(
                observation=self._failed_observation(
                    payload,
                    candidate_id=candidate.candidate_id,
                    failure=FailureInfo(
                        kind=FailureKind.UNSUPPORTED_MODEL,
                        message="; ".join(compatibility.reasons)[:2000],
                    ),
                    evidence_kind=EvidenceKind.NATIVE_MICROBENCH,
                )
            )
        gpu_layers = candidate.parameters.get("gpu_layers", -1)
        needs_gpu = not (
            bundle.engine_id.value == "llamacpp" and isinstance(gpu_layers, int) and gpu_layers == 0
        )
        gpu_uuids: tuple[str, ...] = ()
        if needs_gpu:
            gpu_uuids = tuple(payload.gpu_uuids) or tuple(self.settings.gpu_uuids)
            if not gpu_uuids and self._last_scan and self._last_scan.snapshot.hardware.gpus:
                gpu_uuids = (self._last_scan.snapshot.hardware.gpus[0].uuid,)
        gpu_lease: GpuLease | None = None
        if gpu_uuids:
            allowed, reasons = gpu_preflight(self.settings, gpu_uuids[0])
            if not allowed:
                return TrialResult(
                    observation=self._failed_observation(
                        payload,
                        candidate_id=candidate.candidate_id,
                        failure=FailureInfo(
                            kind=FailureKind.EXTERNAL_GPU_CONTENTION,
                            message="; ".join(reasons)[:2000],
                        ),
                        evidence_kind=EvidenceKind.NATIVE_MICROBENCH,
                    )
                )
            gpu_lease = self.leases.acquire(gpu_uuids, command_id=lease.command.command_id)
        sandbox = create_sandbox(self.settings, lease.command.command_id)
        cancel_event = Event()
        with self._lock:
            self._active[payload.experiment_id] = cancel_event
        on_tick = self._renew_callback(lease)
        native_run: RunResult | None = None
        native_text = ""
        server_run: RunResult | None = None
        serving = None
        server: ServerProcess | None = None
        server_port = allocate_loopback_port()
        try:
            if bundle.engine_id.value == "llamacpp" and bundle.bench_binary is not None:
                native_plan = bundle.adapter.build_microbench_plan(
                    candidate,
                    sandbox,
                    binary=bundle.bench_binary,
                    model=model,
                    repetitions=1,
                )
                native_run = self.runner.run_to_completion(
                    command_id=f"{lease.command.command_id}-native",
                    stage="native-microbench",
                    command=native_plan.stages[0].command,
                    sandbox=sandbox,
                    lease=gpu_lease,
                    cancel_event=cancel_event,
                    on_tick=on_tick,
                )
                native_text = native_run.stdout_text()
            if not cancel_event.is_set():
                if bundle.server_binary is None:
                    raise RealExecutionError(
                        f"engine {bundle.engine_id.value!r} has no observed server binary"
                    )
                server_plan = bundle.adapter.build_server_plan(
                    candidate,
                    sandbox,
                    binary=bundle.server_binary,
                    model=model,
                    port=server_port,
                )
                _write_generated_files(server_plan, Path(sandbox.work_dir))
                server, server_run = self.runner.start_server(
                    command_id=f"{lease.command.command_id}-server",
                    stage="server-lane",
                    command=server_plan.start.command,
                    sandbox=sandbox,
                    lease=gpu_lease,
                    port=server_port,
                    cancel_event=cancel_event,
                    on_tick=on_tick,
                )
                if server is not None:
                    serving = run_serving_workload(
                        self.settings,
                        port=server_port,
                        model_name=str(model.metadata.get("model_name") or model.model_id),
                        context_tokens=int(candidate.context),
                        output_tokens=128,
                        gpu_uuid=gpu_lease.uuid_list[0] if gpu_lease and gpu_lease.uuid_list else None,
                        pid=server._process.pid,
                        timeout_seconds=max(120.0, int(candidate.context) / 32.0),
                        on_tick=on_tick,
                        cancel_event=cancel_event,
                    )
        finally:
            if server is not None:
                server.stop()
            if gpu_lease is not None:
                gpu_lease.release()
            with self._lock:
                self._active.pop(payload.experiment_id, None)

        return TrialResult(
            observation=self._build_trial_observation(
                payload=payload,
                candidate=candidate,
                native_run=native_run,
                native_text=native_text,
                server_run=server_run,
                serving=serving,
                cancel_event=cancel_event,
                model=model,
            )
        )

    # ------------------------------------------------------------ observation
    def _build_trial_observation(
        self,
        *,
        payload: ClaimTrialPayload,
        candidate: CandidateSpec,
        native_run: RunResult | None,
        native_text: str,
        server_run: RunResult | None,
        serving: Any | None,
        cancel_event: Event,
        model: ModelArtifact,
    ) -> BenchmarkObservation:
        raw: list[RawEvidenceRef] = []
        metrics = BenchMetrics()
        notes: list[str] = []
        failure: FailureInfo | None = None
        status = ObservationStatus.COMPLETED
        measurement = MeasurementStatus.UNAVAILABLE
        evidence_kind = EvidenceKind.SERVER_API if server_run is not None else EvidenceKind.NATIVE_MICROBENCH
        effective = None
        input_tokens = None
        output_tokens = None
        quality: list[QualityGate] = []
        telemetry = TelemetryCoverage(source="nvidia-smi+psutil", coverage=0.0)
        telemetry_summary = TelemetrySummary()

        if native_run is not None:
            raw.extend(native_run.artifacts)
            if native_run.telemetry.samples:
                telemetry_summary.samples.extend(native_run.telemetry.samples)
                telemetry_summary.errors.extend(native_run.telemetry.errors)
                metrics = metrics.model_copy(
                    update={
                        "gpu_vram_peak_bytes": native_run.telemetry.vram_peak_bytes,
                        "cpu_rss_peak_bytes": native_run.telemetry.rss_peak_bytes,
                        "system_ram_available_min_bytes": native_run.telemetry.ram_min_bytes,
                        "gpu_utilization": native_run.telemetry.utilization_avg,
                        "gpu_temperature_max_c": native_run.telemetry.temperature_max_c,
                        "gpu_power_average_w": native_run.telemetry.power_avg_w,
                        "gpu_sm_clock_mhz": native_run.telemetry.sm_clock_max_mhz,
                        "gpu_mem_clock_mhz": native_run.telemetry.mem_clock_max_mhz,
                    }
                )
                telemetry = TelemetryCoverage(
                    source="nvidia-smi+psutil",
                    sample_interval_ms=self.settings.telemetry_interval_ms,
                    samples=len(native_run.telemetry.samples),
                    coverage=native_run.telemetry.coverage(),
                    notes=tuple(native_run.telemetry.errors),
                )
            if native_run.succeeded and native_text:
                try:
                    micro = self._bundle(payload.engine.engine_id.value).adapter.parse_microbench_evidence(
                        RawEvidence(
                            evidence_id=f"{payload.candidate_id}-native",
                            path=native_run.stdout_path,
                            content_type="application/json",
                            text=native_text,
                            sha256=sha256_hex(native_text),
                        ),
                        candidate,
                    )
                    prefill = micro.prefill_row()
                    decode = micro.decode_row()
                    mixed = micro.mixed_row()
                    if prefill is not None or decode is not None or mixed is not None:
                        metrics = metrics.model_copy(
                            update={
                                "prefill_tokens_per_sec": prefill.avg_ts if prefill else None,
                                "decode_tokens_per_sec": decode.avg_ts if decode else None,
                            }
                        )
                        notes.append("native llama-bench evidence parsed; missing rows remain missing")
                except Exception as exc:
                    notes.append(f"native evidence parser refused the run: {type(exc).__name__}: {exc}")
            elif native_run.succeeded is False:
                notes.append(native_run.error or "native microbench did not complete")

        if server_run is not None:
            raw.extend(server_run.artifacts)
            telemetry_summary.samples.extend(server_run.telemetry.samples)
            telemetry_summary.errors.extend(server_run.telemetry.errors)
        if serving is not None:
            raw.extend(server_run.artifacts if server_run else ())
            telemetry_summary.samples.extend(serving.telemetry.samples)
            telemetry_summary.errors.extend(serving.telemetry.errors)
            if serving.status_document:
                # The adapter owns engine-specific interpretation of /props or
                # /v1/status. It may fill context identity, never client-observed
                # throughput or a peak VRAM value.
                try:
                    parsed_status = self._bundle(
                        payload.engine.engine_id.value
                    ).adapter.parse_server_evidence(
                        RawEvidence(
                            evidence_id=f"{payload.candidate_id}-status",
                            path=f"server-status:{payload.candidate_id}",
                            content_type="application/json",
                            text=json.dumps(serving.status_document, sort_keys=True),
                        ),
                        None,
                        candidate,
                    )
                    if effective is None:
                        effective = parsed_status.context_effective
                    notes.append(
                        "server status parsed by the engine adapter for context identity; "
                        "client-observed throughput keeps precedence"
                    )
                except Exception as exc:
                    notes.append(f"server status parser refused the document: {type(exc).__name__}: {exc}")
            if serving.completed:
                derived = derive_serving_metrics(serving)
                metrics = metrics.model_copy(
                    update={
                        "time_to_first_token_ms": derived["time_to_first_token_ms"],
                        "total_latency_ms": derived["total_latency_ms"],
                        "prefill_tokens_per_sec": derived["prefill_tokens_per_sec"]
                        if metrics.prefill_tokens_per_sec is None
                        else metrics.prefill_tokens_per_sec,
                        "decode_tokens_per_sec": derived["decode_tokens_per_sec"]
                        if metrics.decode_tokens_per_sec is None
                        else metrics.decode_tokens_per_sec,
                    }
                )
                effective = serving.effective_context
                input_tokens = serving.prompt_tokens
                output_tokens = serving.output_tokens
                if serving.text_preview:
                    quality.append(
                        QualityGate(
                            name="non_empty_output",
                            status=QualityGateStatus.PASSED,
                            details="one deterministic streaming completion returned text",
                        )
                    )
                else:
                    quality.append(
                        QualityGate(
                            name="non_empty_output",
                            status=QualityGateStatus.FAILED,
                            details="stream completed without any content token",
                        )
                    )
                if effective is not None:
                    quality.append(
                        QualityGate(
                            name="effective_context",
                            status=QualityGateStatus.PASSED
                            if effective >= int(payload.context)
                            else QualityGateStatus.FAILED,
                            score=float(effective),
                            threshold=float(int(payload.context)),
                            details="server-reported effective context",
                        )
                    )
                if metrics.time_to_first_token_ms is not None and metrics.total_latency_ms is not None:
                    measurement = MeasurementStatus.MEASURED
                else:
                    measurement = MeasurementStatus.UNAVAILABLE
                    notes.append(
                        "server usage did not expose both client-side metrics; values were not invented"
                    )
            else:
                notes.append(serving.error or "serving workload failed")
        else:
            quality.append(
                QualityGate(
                    name="serving_lane",
                    status=QualityGateStatus.NOT_RUN,
                    details="the OpenAI-compatible serving lane did not complete",
                )
            )
            if native_run is not None and native_run.succeeded:
                measurement = MeasurementStatus.SCREENING_ONLY
                notes.append("screening-only native evidence; no serving-lane measurement")

        native_ok = native_run is not None and native_run.succeeded
        server_ok = serving is not None and serving.completed
        native_failed = native_run is not None and not native_run.succeeded
        server_failed = server_run is not None and not server_run.succeeded and not server_ok
        if cancel_event.is_set():
            status = ObservationStatus.CANCELLED
            measurement = MeasurementStatus.INVALID
            failure = FailureInfo(kind=FailureKind.CANCELLED, message="operator cancelled the trial")
        elif not native_ok and not server_ok:
            failed = [run for run in (native_run, server_run) if run is not None]
            text = "\n".join(run.stdout_text() + "\n" + run.stderr_text() for run in failed)
            kind, stage = _failure_kind(
                text,
                cancelled=any(run.cancelled for run in failed),
                timed_out=any(run.timed_out for run in failed),
            )
            status = (
                ObservationStatus.RESOURCE_INFEASIBLE
                if kind
                in {
                    FailureKind.INSUFFICIENT_VRAM,
                    FailureKind.INSUFFICIENT_RAM,
                    FailureKind.OOM,
                }
                else ObservationStatus.FAILED
            )
            measurement = (
                MeasurementStatus.INFEASIBLE
                if status is ObservationStatus.RESOURCE_INFEASIBLE
                else MeasurementStatus.INVALID
            )
            failed_run = failed[-1] if failed else None
            serving_error = getattr(serving, "error", None)
            if serving_error and kind is FailureKind.UNKNOWN:
                kind = FailureKind.SERVER_NOT_READY
            failure = FailureInfo(
                kind=kind,
                stage=stage,
                message=(
                    serving_error or (failed_run.error if failed_run else None) or "trial process failed"
                )[:2000],
                retryable=kind in {FailureKind.TIMEOUT, FailureKind.EXTERNAL_GPU_CONTENTION},
                process_exit_code=failed_run.exit_code if failed_run else None,
                sanitized_log_ref=failed_run.stderr_path if failed_run else None,
            )
        elif native_failed:
            notes.append(
                "native microbench failed but the serving lane completed; native metrics were left missing"
            )
        elif server_failed:
            notes.append("serving lane failed but native microbench completed; this trial is screening-only")

        if telemetry_summary.samples:
            telemetry = TelemetryCoverage(
                source="nvidia-smi+psutil",
                sample_interval_ms=self.settings.telemetry_interval_ms,
                samples=len(telemetry_summary.samples),
                coverage=telemetry_summary.coverage(),
                notes=tuple(dict.fromkeys(telemetry_summary.errors)),
            )
            observed = {
                "gpu_vram_peak_bytes": telemetry_summary.vram_peak_bytes,
                "cpu_rss_peak_bytes": telemetry_summary.rss_peak_bytes,
                "system_ram_available_min_bytes": telemetry_summary.ram_min_bytes,
                "gpu_utilization": telemetry_summary.utilization_avg,
                "gpu_temperature_max_c": telemetry_summary.temperature_max_c,
                "gpu_power_average_w": telemetry_summary.power_avg_w,
                "gpu_sm_clock_mhz": telemetry_summary.sm_clock_max_mhz,
                "gpu_mem_clock_mhz": telemetry_summary.mem_clock_max_mhz,
            }
            updates = {
                key: value
                for key, value in observed.items()
                if value is not None and getattr(metrics, key) is None
            }
            if updates:
                metrics = metrics.model_copy(update=updates)
            if telemetry_summary.errors:
                notes.append(
                    "telemetry sampling reported errors: "
                    + "; ".join(dict.fromkeys(telemetry_summary.errors))
                )

        if measurement is MeasurementStatus.SCREENING_ONLY and metrics.missing(
            ("prefill_tokens_per_sec", "decode_tokens_per_sec")
        ):
            measurement = MeasurementStatus.UNAVAILABLE
            notes.append("screening-only evidence lacked required native metrics; status was downgraded")

        if (
            metrics.missing(("time_to_first_token_ms", "total_latency_ms"))
            and measurement is MeasurementStatus.MEASURED
        ):
            measurement = MeasurementStatus.UNAVAILABLE
            notes.append("required serving metrics were incomplete; measurement status was downgraded")
        if (
            status is ObservationStatus.COMPLETED
            and measurement is MeasurementStatus.MEASURED
            and effective is None
        ):
            measurement = MeasurementStatus.SCREENING_ONLY
            notes.append("effective context was not reported; measured throughput alone is screening-only")

        return BenchmarkObservation(
            experiment_id=payload.experiment_id,
            study_id=payload.study_id,
            candidate_id=candidate.candidate_id,
            trial_number=int(payload.trial_number),
            attempt=0,
            worker_id=self.settings.worker_id,
            engine_id=payload.engine.engine_id.value,
            engine_sha256=payload.engine.executable_sha256,
            model_digest=model.artifact_digest,
            workload_digest=payload.workload_digest,
            context=payload.context,
            evidence_kind=evidence_kind,
            measurement_status=measurement,
            status=status,
            metrics=metrics,
            configured_context=int(payload.context),
            effective_context=effective,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            repetitions=1,
            telemetry=telemetry,
            quality_gates=tuple(quality),
            failure=failure,
            raw_evidence=_combine_evidence(tuple(raw)),
            simulated=False,
            notes=(
                *notes,
                f"real worker {self.settings.worker_id}",
                f"engine sha256 {payload.engine.executable_sha256}",
            ),
        )

    def _failed_observation(
        self,
        payload: ClaimTrialPayload,
        *,
        candidate_id: str,
        failure: FailureInfo,
        evidence_kind: EvidenceKind,
    ) -> BenchmarkObservation:
        return BenchmarkObservation(
            experiment_id=payload.experiment_id,
            study_id=payload.study_id,
            candidate_id=candidate_id,
            trial_number=int(payload.trial_number),
            attempt=0,
            worker_id=self.settings.worker_id,
            engine_id=payload.engine.engine_id.value,
            engine_sha256=payload.engine.executable_sha256,
            model_digest=payload.model.artifact_digest,
            workload_digest=payload.workload_digest,
            context=payload.context,
            evidence_kind=evidence_kind,
            measurement_status=MeasurementStatus.INVALID,
            status=ObservationStatus.FAILED,
            failure=failure,
            simulated=False,
            notes=("real worker rejected the candidate before spawning a process",),
        )

    def _hardware_for_compat(self) -> Any:
        from .hardware import collect_hardware

        return collect_hardware(self.settings)

    # --------------------------------------------------------------- lifecycle
    def _pause(self, payload: PausePayload) -> PauseResult:
        with self._lock:
            event = self._active.get(payload.experiment_id)
        if event is not None:
            event.set()
        return PauseResult(
            experiment_id=payload.experiment_id,
            accepted=True,
            paused_at_stage="process" if event is not None else None,
            message="current owned process group will stop at the next safe boundary",
        )

    def _cancel(self, payload: CancelPayload) -> CancelResult:
        with self._lock:
            event = self._active.get(payload.experiment_id)
        if event is not None:
            event.set()
        return CancelResult(
            experiment_id=payload.experiment_id,
            accepted=True,
            message=(
                "cancellation requested; only processes started by this worker are terminated"
                if event is not None
                else "no active owned process for this experiment"
            ),
        )

    # ---------------------------------------------------------------- recipes
    def _verify(self, payload: VerifyRecipePayload) -> VerifyRecipeResult:
        mismatches: list[str] = []
        if self._last_scan is None:
            mismatches.append("no current worker inventory snapshot")
            return VerifyRecipeResult(
                recipe_id=payload.recipe_id,
                verified=False,
                mismatches=tuple(mismatches),
                message="run SCAN before verifying a recipe",
            )
        engine_ok = any(
            engine.engine.executable_sha256 == payload.expected_engine_sha256
            for engine in self._last_scan.snapshot.engines
        )
        if not engine_ok:
            mismatches.append("engine executable digest does not match")
        model_ok = any(
            model.artifact_digest == payload.expected_model_digest
            for model in self._last_scan.snapshot.models
        )
        if not model_ok:
            mismatches.append("model artifact digest does not match")
        return VerifyRecipeResult(
            recipe_id=payload.recipe_id,
            verified=not mismatches,
            engine_sha256=payload.expected_engine_sha256 if engine_ok else None,
            model_digest=payload.expected_model_digest if model_ok else None,
            mismatches=tuple(mismatches),
            message="recipe identities match the current inventory"
            if not mismatches
            else "identity mismatch",
        )

    def _promote(self, payload: PromotePayload) -> PromoteResult:
        return PromoteResult(
            recipe_id=payload.recipe_id,
            promoted=False,
            dry_run=payload.dry_run,
            slot=payload.target_slot,
            message=(
                "dry-run only: this worker does not mutate an operator-owned deployment slot"
                if payload.dry_run
                else "live promotion is operator-owned and was not performed"
            ),
        )


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False
