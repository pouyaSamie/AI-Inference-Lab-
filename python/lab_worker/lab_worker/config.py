"""Configuration for the Phase 1 worker.

The same daemon shell is used by the explicit simulated worker. Phase 2 will
add real process execution behind the same durable command protocol.
"""

from __future__ import annotations

from pathlib import Path

from lab_core.version import SCHEMA_VERSION, WORKER_PROTOCOL_VERSION
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LAB_WORKER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    controller_url: str = "http://127.0.0.1:8787"
    enrollment_token: str = ""
    worker_token: str = ""
    worker_id: str = "sim-worker-1"
    worker_name: str = "Phase 1 simulated worker"
    worker_version: str = SCHEMA_VERSION
    protocol_version: str = WORKER_PROTOCOL_VERSION
    state_file: str = "var/sim-worker-state.json"

    model_id: str = "qwen2.5-7b-instruct-q4_k_m"
    model_path: str = "/home/pouya/ai-lab/models/qwen2.5-7b-instruct-q4_k_m.gguf"
    model_size_bytes: int = 4_680_000_000
    model_context_tokens: int = 32768

    engine_id: str = "llamacpp"
    engine_path: str = "/home/pouya/ai-lab/Inference/llama-cpp/builds/linux/latest-candidate/bin/llama-server"
    llama_bench_path: str = (
        "/home/pouya/ai-lab/Inference/llama-cpp/builds/linux/latest-candidate/bin/llama-bench"
    )

    poll_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    heartbeat_seconds: float = Field(default=10.0, ge=1.0, le=300.0)
    sweep_seconds: float = Field(default=300.0, ge=10.0)
    max_commands: int = Field(default=3, ge=1, le=50)
    max_iterations: int | None = Field(default=None, ge=1)
    simulated: bool = True

    @property
    def state_path(self) -> Path:
        return Path(self.state_file).expanduser()
