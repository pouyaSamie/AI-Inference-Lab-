"""Configuration for the supervised optimizer process."""

from __future__ import annotations

import os
import socket
from pathlib import Path

from lab_core.version import OPTIMIZER_PROTOCOL_VERSION, SCHEMA_VERSION
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class OptimizerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LAB_OPTIMIZER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    controller_url: str = "http://127.0.0.1:8787"
    token: SecretStr = SecretStr("")
    db_url: str = "sqlite:///./var/optuna.sqlite3"
    optimizer_id: str | None = None
    heartbeat_seconds: float = Field(default=10.0, ge=1.0, le=300.0)
    poll_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    poll_max_requests: int = Field(default=5, ge=1, le=50)
    max_iterations: int | None = Field(default=None, ge=1)
    log_level: str = "INFO"
    version: str = SCHEMA_VERSION
    protocol_version: str = OPTIMIZER_PROTOCOL_VERSION

    @model_validator(mode="after")
    def _validate(self) -> OptimizerSettings:
        parsed = make_url(self.db_url)
        if parsed.get_backend_name() != "sqlite":
            raise ValueError("Phase 1 optimizer storage must be SQLite")
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        return self

    def validate_runtime(self) -> None:
        if not self.token.get_secret_value():
            raise ValueError("LAB_OPTIMIZER_TOKEN is required")
        if len(self.token.get_secret_value()) < 16:
            raise ValueError("optimizer token must be at least 16 characters")

    def resolved_optimizer_id(self) -> str:
        return self.optimizer_id or f"opt_{socket.gethostname()}_{os.getpid()}"
