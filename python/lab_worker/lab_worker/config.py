"""Configuration for the real and simulated Linux workers.

The simulated lane keeps its deterministic fixture inventory. The real lane
uses only configured, operator-approved roots and observed installed binaries;
it never downloads, replaces or mutates engines or model weights.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from lab_core.version import SCHEMA_VERSION, WORKER_PROTOCOL_VERSION
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LAB_WORKER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------- controller
    controller_url: str = "http://127.0.0.1:8787"
    enrollment_token: str = ""
    worker_token: str = ""
    worker_id: str = "linux-worker-1"
    worker_name: str = "Linux inference worker"
    worker_version: str = SCHEMA_VERSION
    protocol_version: str = WORKER_PROTOCOL_VERSION
    state_file: str = "var/worker-state.json"

    # --------------------------------------------------------------- identity
    execution_mode: Literal["simulated", "real"] = "real"
    simulated: bool = False
    supported_engines: list[str] = Field(default_factory=lambda: ["llamacpp", "strata"])

    # ----------------------------------------------------------- model roots
    model_roots: list[str] = Field(default_factory=lambda: ["/home/pouya/ai-lab/models"])
    state_root: str = "var/worker"
    sandbox_root: str | None = None
    journal_root: str | None = None
    lease_root: str | None = None
    artifact_root: str | None = None
    hash_cache_path: str | None = None
    hashing_enabled: bool = True
    follow_symlinks: bool = False
    max_scan_depth: int = Field(default=6, ge=1, le=32)

    # --------------------------------------------------------------- engines
    llama_server_path: str = (
        "/home/pouya/ai-lab/Inference/llama-cpp/builds/linux/latest-candidate/bin/llama-server"
    )
    llama_bench_path: str = (
        "/home/pouya/ai-lab/Inference/llama-cpp/builds/linux/latest-candidate/bin/llama-bench"
    )
    llama_lib_dir: str = "/home/pouya/ai-lab/Inference/llama-cpp/builds/linux/latest-candidate/bin"
    strata_path: str = "/home/pouya/ai-lab/Inference/strata/builds/linux/v0.1.44.1-candidate/strata"
    strata_source_root: str = "/home/pouya/ai-lab/Inference/strata/source"
    strata_server_script: str = "/home/pouya/ai-lab/Inference/strata/source/serve/server.py"
    strata_python: str = Field(default_factory=lambda: sys.executable)
    probe_timeout_seconds: int = Field(default=20, ge=1, le=300)

    # Backwards-compatible simulate fields; the explicit simulated lane uses
    # these to build deterministic fixture inventory.
    model_id: str = "qwen2.5-7b-instruct-q4_k_m"
    model_path: str = "/home/pouya/ai-lab/models/qwen2.5-7b-instruct-q4_k_m.gguf"
    model_size_bytes: int = 4_680_000_000
    model_context_tokens: int = 32768
    engine_id: str = "llamacpp"
    engine_path: str = "/home/pouya/ai-lab/Inference/llama-cpp/builds/linux/latest-candidate/bin/llama-server"

    # ------------------------------------------------------------- scheduling
    poll_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    heartbeat_seconds: float = Field(default=10.0, ge=1.0, le=300.0)
    lease_renew_seconds: float = Field(default=30.0, ge=2.0, le=900.0)
    sweep_seconds: float = Field(default=300.0, ge=10.0)
    max_commands: int = Field(default=1, ge=1, le=50)
    max_iterations: int | None = Field(default=None, ge=1)

    # -------------------------------------------------------------- lifecycle
    command_grace_seconds: int = Field(default=15, ge=1, le=300)
    readiness_poll_ms: int = Field(default=250, ge=50, le=5000)
    server_ready_timeout_seconds: int = Field(default=180, ge=10, le=1800)
    trial_timeout_seconds: int = Field(default=3600, ge=30, le=86_400)
    telemetry_interval_ms: int = Field(default=500, ge=100, le=10_000)
    keep_sandboxes: int = Field(default=50, ge=0, le=1000)

    # ------------------------------------------------------------------- GPU
    gpu_uuids: list[str] = Field(default_factory=list)
    min_free_vram_bytes: int = Field(default=1_500_000_000, ge=0)
    max_gpu_utilization_pct: int = Field(default=20, ge=0, le=100)
    max_gpu_temperature_c: float = Field(default=85.0, ge=30.0, le=120.0)
    gpu_settle_seconds: int = Field(default=3, ge=0, le=60)
    external_compute_process_allowlist: list[str] = Field(
        default_factory=lambda: ["gnome-remote-desktop-daemon", "ptyxis", "Xorg", "Xwayland"]
    )

    # ---------------------------------------------------------------- limits
    max_model_files: int = Field(default=64, ge=1, le=1024)
    max_strata_packs: int = Field(default=32, ge=1, le=512)

    @model_validator(mode="after")
    def _paths_are_absolute(self) -> WorkerSettings:
        for value in self.model_roots:
            path = Path(value).expanduser()
            if not path.is_absolute():
                raise ValueError(f"model root must be absolute: {value!r}")
            if ".." in path.parts:
                raise ValueError(f"model root must not contain '..': {value!r}")
        for name in ("llama_lib_dir", "state_root"):
            configured = Path(getattr(self, name)).expanduser()
            if not configured.is_absolute() and name != "state_root":
                raise ValueError(f"{name} must be absolute")
        if self.lease_renew_seconds >= 180:
            raise ValueError("lease_renew_seconds must be below 180 seconds")
        return self

    # -------------------------------------------------------------- resolved
    @property
    def state_path(self) -> Path:
        return Path(self.state_file).expanduser()

    @property
    def resolved_state_root(self) -> Path:
        return Path(self.state_root).expanduser().resolve()

    @property
    def resolved_sandbox_root(self) -> Path:
        return Path(self.sandbox_root or self.resolved_state_root / "sandboxes").expanduser().resolve()

    @property
    def resolved_journal_root(self) -> Path:
        return Path(self.journal_root or self.resolved_state_root / "journal").expanduser().resolve()

    @property
    def resolved_lease_root(self) -> Path:
        return Path(self.lease_root or self.resolved_state_root / "gpu-leases").expanduser().resolve()

    @property
    def resolved_artifact_root(self) -> Path:
        return Path(self.artifact_root or self.resolved_state_root / "artifacts").expanduser().resolve()

    @property
    def resolved_hash_cache(self) -> Path:
        return (
            Path(self.hash_cache_path or self.resolved_state_root / "hash-cache.json").expanduser().resolve()
        )

    @property
    def resolved_run_root(self) -> Path:
        return Path(self.state_root).expanduser().resolve() / "run"

    @property
    def resolved_model_roots(self) -> tuple[Path, ...]:
        roots: list[Path] = []
        for raw in self.model_roots:
            try:
                roots.append(Path(raw).expanduser().resolve(strict=False))
            except OSError:
                continue
        return tuple(dict.fromkeys(roots))

    def ensure_directories(self) -> None:
        for path in (
            self.resolved_state_root,
            self.resolved_sandbox_root,
            self.resolved_journal_root,
            self.resolved_lease_root,
            self.resolved_artifact_root,
            self.resolved_run_root,
        ):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
