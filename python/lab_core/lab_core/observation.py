"""Benchmark observations, required metrics and failure taxonomy."""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import AwareTimestamp, FrozenModel, Identifier, NonEmptyStr, NonNegativeInt, PositiveInt, Probability, Sha256, utcnow
from .enums import (
    ContextLength,
    EvidenceKind,
    FailureKind,
    MeasurementStatus,
    OOMStage,
    ObservationStatus,
    QualityGateStatus,
)
from .execution import RawEvidenceRef
from .ids import sha256_hex, stable_id
from .version import SCHEMA_VERSION, WORKLOAD_PROTOCOL

REQUIRED_NATIVE_METRICS = ("prefill_tokens_per_sec", "decode_tokens_per_sec")
REQUIRED_SERVER_METRICS = ("time_to_first_token_ms", "total_latency_ms")


class BenchMetrics(FrozenModel):
    prefill_tokens_per_sec: float | None = None
    decode_tokens_per_sec: float | None = None
    time_to_first_token_ms: float | None = None
    total_latency_ms: float | None = None
    cold_start_ms: float | None = None
    server_ready_ms: float | None = None
    model_load_sec: float | None = None
    gpu_vram_peak_bytes: int | None = None
    cpu_rss_peak_bytes: int | None = None
    system_ram_available_min_bytes: int | None = None
    gpu_utilization: float | None = None
    gpu_memory_utilization: float | None = None
    gpu_temperature_max_c: float | None = None
    gpu_power_average_w: float | None = None
    gpu_sm_clock_mhz: float | None = None
    gpu_mem_clock_mhz: float | None = None
    energy_joules: float | None = None
    cache_hit: bool | None = None
    unavailable_reasons: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _no_negative(self) -> BenchMetrics:
        for name in (
            "prefill_tokens_per_sec",
            "decode_tokens_per_sec",
            "time_to_first_token_ms",
            "total_latency_ms",
            "cold_start_ms",
            "server_ready_ms",
            "model_load_sec",
            "gpu_vram_peak_bytes",
            "cpu_rss_peak_bytes",
            "system_ram_available_min_bytes",
            "gpu_temperature_max_c",
            "gpu_power_average_w",
            "gpu_sm_clock_mhz",
            "gpu_mem_clock_mhz",
            "energy_joules",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")
        return self

    def missing(self, required: tuple[str, ...]) -> list[str]:
        return [name for name in required if getattr(self, name) is None]


class TelemetryCoverage(FrozenModel):
    source: NonEmptyStr = "none"
    sample_interval_ms: PositiveInt | None = None
    samples: NonNegativeInt = 0
    expected_samples: NonNegativeInt | None = None
    coverage: Probability = 0.0
    notes: tuple[str, ...] = ()


class QualityGate(FrozenModel):
    name: NonEmptyStr
    status: QualityGateStatus
    score: float | None = None
    threshold: float | None = None
    details: str | None = None


class FailureInfo(FrozenModel):
    kind: FailureKind
    stage: OOMStage = OOMStage.UNKNOWN
    message: NonEmptyStr
    retryable: bool = False
    process_exit_code: int | None = None
    sanitized_log_ref: str | None = None


class BenchmarkObservation(FrozenModel):
    """Immutable normalized evidence for one candidate/context/attempt.

    ``observation_id`` is deterministic over candidate, attempt, evidence
    lane and context. The controller uses it as the idempotency key for
    duplicate worker completions.
    """

    schema_version: NonEmptyStr = SCHEMA_VERSION
    observation_id: Identifier = ""
    experiment_id: Identifier
    study_id: Identifier
    candidate_id: Identifier
    trial_number: NonNegativeInt
    attempt: NonNegativeInt = 0
    worker_id: Identifier
    engine_id: NonEmptyStr
    engine_sha256: Sha256
    model_digest: Sha256
    workload_digest: Sha256
    context: ContextLength
    protocol: NonEmptyStr = WORKLOAD_PROTOCOL
    evidence_kind: EvidenceKind
    measurement_status: MeasurementStatus
    status: ObservationStatus
    metrics: BenchMetrics = Field(default_factory=BenchMetrics)
    configured_context: int | None = None
    effective_context: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    repetitions: PositiveInt = 1
    dispersion: dict[str, float] = Field(default_factory=dict)
    telemetry: TelemetryCoverage = Field(default_factory=TelemetryCoverage)
    quality_gates: tuple[QualityGate, ...] = ()
    failure: FailureInfo | None = None
    raw_evidence: tuple[RawEvidenceRef, ...] = ()
    simulated: bool = False
    observed_at: AwareTimestamp = Field(default_factory=utcnow)
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _fill_observation_id(self) -> BenchmarkObservation:
        expected = stable_id(
            "obs",
            self.candidate_id,
            self.attempt,
            self.evidence_kind.value,
            int(self.context),
        )
        if self.observation_id and self.observation_id != expected:
            raise ValueError("observation_id does not match candidate/attempt/context identity")
        object.__setattr__(self, "observation_id", expected)
        if self.status is ObservationStatus.COMPLETED and self.measurement_status in (
            MeasurementStatus.MEASURED,
            MeasurementStatus.SIMULATED,
            MeasurementStatus.SCREENING_ONLY,
        ):
            required = REQUIRED_NATIVE_METRICS if self.evidence_kind is EvidenceKind.NATIVE_MICROBENCH else REQUIRED_SERVER_METRICS
            missing = self.metrics.missing(required)
            if missing:
                raise ValueError(f"completed observation is missing required metrics: {missing}")
        if self.status is not ObservationStatus.COMPLETED and self.failure is None:
            raise ValueError("non-completed observation requires failure details")
        return self

    def content_digest(self) -> str:
        return sha256_hex(
            self.model_dump(
                mode="json",
                exclude={"observed_at", "raw_evidence", "notes"},
            )
        )

    def scoring_eligibility(self) -> list[str]:
        """Reasons the observation cannot be scored for a validated recipe."""
        reasons: list[str] = []
        if self.simulated:
            reasons.append("SIMULATED_EVIDENCE")
        if self.status is not ObservationStatus.COMPLETED:
            reasons.append(f"STATUS_{self.status.value.upper()}")
        if self.measurement_status is not MeasurementStatus.MEASURED:
            reasons.append(f"MEASUREMENT_{self.measurement_status.value.upper()}")
        if self.context is ContextLength.K128 and self.effective_context is not None and self.effective_context < int(self.context):
            reasons.append("CONTEXT_TRUNCATED")
        if self.configured_context is not None and self.effective_context is not None and self.effective_context < self.configured_context:
            reasons.append("EFFECTIVE_CONTEXT_BELOW_CONFIGURED")
        for gate in self.quality_gates:
            if gate.status is QualityGateStatus.FAILED:
                reasons.append(f"QUALITY_GATE_FAILED:{gate.name}")
        return reasons


class MicrobenchRow(FrozenModel):
    test: NonEmptyStr
    n_prompt: NonNegativeInt = 0
    n_gen: NonNegativeInt = 0
    n_depth: NonNegativeInt = 0
    avg_ts: float | None = None
    stddev_ts: float | None = None
    samples_ts: tuple[float, ...] = ()
    n_threads: int | None = None
    n_gpu_layers: int | None = None
    type_k: str | None = None
    type_v: str | None = None
    flash_attn: str | None = None
    n_batch: int | None = None
    n_ubatch: int | None = None
    n_cpu_moe: int | None = None

    @model_validator(mode="after")
    def _throughput(self) -> MicrobenchRow:
        if self.avg_ts is not None and self.avg_ts < 0:
            raise ValueError("throughput must not be negative")
        return self


class MicrobenchObservation(FrozenModel):
    engine_id: NonEmptyStr
    build_commit: str | None = None
    build_number: str | None = None
    model_filename: str | None = None
    model_type: str | None = None
    backends: str | None = None
    gpu_info: str | None = None
    rows: tuple[MicrobenchRow, ...]
    raw_sha256: Sha256
    parsed_at: AwareTimestamp = Field(default_factory=utcnow)
    warnings: tuple[str, ...] = ()

    def prefill_row(self) -> MicrobenchRow | None:
        return next((row for row in self.rows if row.n_prompt > 0 and row.n_gen == 0), None)

    def decode_row(self) -> MicrobenchRow | None:
        return next((row for row in self.rows if row.n_gen > 0 and row.n_prompt == 0), None)

    def mixed_row(self) -> MicrobenchRow | None:
        return next((row for row in self.rows if row.n_prompt > 0 and row.n_gen > 0), None)


class ServingObservation(FrozenModel):
    engine_id: NonEmptyStr
    status_sha256: Sha256
    metrics_sha256: Sha256 | None = None
    context_configured: int | None = None
    context_effective: int | None = None
    prefill_tokens_per_sec: float | None = None
    decode_tokens_per_sec: float | None = None
    time_to_first_token_ms: float | None = None
    total_latency_ms: float | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    cache_hit: bool | None = None
    gpu_vram_used_bytes: int | None = None
    gpu_utilization: float | None = None
    gpu_temperature_c: float | None = None
    unavailable_reasons: dict[str, str] = Field(default_factory=dict)
    parsed_at: AwareTimestamp = Field(default_factory=utcnow)
    warnings: tuple[str, ...] = ()


class FeasibilityObservation(FrozenModel):
    study_id: Identifier
    candidate_digest: Sha256
    outcome: str
    oom_stage: OOMStage = OOMStage.UNKNOWN
    assumption_signature: Sha256
    observed_vram_bytes: int | None = None
    observed_ram_bytes: int | None = None
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    created_at: AwareTimestamp = Field(default_factory=utcnow)
    note: str | None = None
