"""Controller configuration with explicit startup validation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LAB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "lab-controller"
    environment: Literal["dev", "test", "prod"] = "dev"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8787, ge=1, le=65535)
    log_level: str = "INFO"

    controller_db_url: str = "sqlite:///./var/controller.sqlite3"
    optimizer_db_url: str = "sqlite:///./var/optuna.sqlite3"
    sqlite_busy_timeout_ms: int = Field(default=10_000, ge=1000, le=120_000)
    sqlite_synchronous: Literal["FULL", "NORMAL"] = "FULL"

    operator_token: SecretStr = SecretStr("")
    enrollment_token: SecretStr = SecretStr("")
    optimizer_token: SecretStr = SecretStr("")
    worker_token_pepper: SecretStr = SecretStr("")
    min_token_length: int = Field(default=16, ge=8)

    worker_lease_seconds: int = Field(default=120, ge=5, le=3600)
    worker_offline_after_seconds: int = Field(default=120, ge=5, le=86_400)
    snapshot_max_age_seconds: int = Field(default=86_400, ge=60, le=2_592_000)
    command_max_attempts: int = Field(default=5, ge=1, le=100)
    trial_timeout_seconds: int = Field(default=7200, ge=30, le=86_400)
    max_command_batch: int = Field(default=5, ge=1, le=50)

    optimizer_lease_seconds: int = Field(default=60, ge=5, le=3600)
    optimizer_offline_after_seconds: int = Field(default=30, ge=5, le=3600)
    optimizer_poll_wait_seconds: int = Field(default=20, ge=0, le=55)
    optimizer_max_attempts: int = Field(default=8, ge=1, le=100)

    scheduler_enabled: bool = True
    scheduler_interval_seconds: float = Field(default=0.5, ge=0.05, le=60)
    sse_poll_interval_seconds: float = Field(default=0.25, ge=0.05, le=5.0)
    sse_batch_size: int = Field(default=200, ge=1, le=2000)
    sse_keepalive_seconds: int = Field(default=15, ge=1, le=120)
    event_retention_events_per_experiment: int = Field(default=50_000, ge=100)

    artifact_root: str = "var/artifacts"
    allowed_model_roots: list[str] = Field(default_factory=lambda: ["/home/pouya/ai-lab/models"])
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    allow_simulation: bool = True
    execution_mode: Literal["simulated", "real"] = "simulated"
    document_openapi: bool = True

    @model_validator(mode="after")
    def _database_separation(self) -> Settings:
        controller = make_url(self.controller_db_url)
        optimizer = make_url(self.optimizer_db_url)
        if self.controller_db_url == self.optimizer_db_url:
            raise ValueError("controller and optimizer databases must be separate")
        if (
            controller.get_backend_name() == "sqlite"
            and optimizer.get_backend_name() == "sqlite"
            and controller.database
            and optimizer.database
        ):
            controller_path = Path(controller.database).resolve()
            optimizer_path = Path(optimizer.database).resolve()
            if controller_path == optimizer_path:
                raise ValueError("controller and optimizer must not share a SQLite file")
        return self

    def validate_runtime(self) -> None:
        missing: list[str] = []
        for name in ("operator_token", "enrollment_token", "optimizer_token", "worker_token_pepper"):
            value = getattr(self, name).get_secret_value()
            if not value:
                missing.append(name.upper())
            elif len(value) < self.min_token_length:
                raise ValueError(f"{name} must be at least {self.min_token_length} characters")
        if missing:
            raise ValueError(
                "missing required secrets: " + ", ".join(missing) + ". "
                "Set LAB_OPERATOR_TOKEN, LAB_ENROLLMENT_TOKEN, LAB_OPTIMIZER_TOKEN and "
                "LAB_WORKER_TOKEN_PEPPER (see .env.example)."
            )

    def ensure_directories(self) -> None:
        for url in (self.controller_db_url, self.optimizer_db_url):
            parsed = make_url(url)
            if parsed.get_backend_name() == "sqlite" and parsed.database and parsed.database != ":memory:":
                Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        Path(self.artifact_root).expanduser().resolve().mkdir(parents=True, exist_ok=True)

    def safe_summary(self) -> dict[str, object]:
        return {
            "environment": self.environment,
            "api_host": self.api_host,
            "api_port": self.api_port,
            "controller_db": make_url(self.controller_db_url).render_as_string(hide_password=True),
            "optimizer_db": make_url(self.optimizer_db_url).render_as_string(hide_password=True),
            "scheduler_enabled": self.scheduler_enabled,
            "allow_simulation": self.allow_simulation,
            "execution_mode": self.execution_mode,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
