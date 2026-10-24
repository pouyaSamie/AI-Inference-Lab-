"""Bounded contracts for explicitly started, lab-owned local serving sessions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import AwareTimestamp, FrozenModel, Identifier, NonEmptyStr


class ServingSession(FrozenModel):
    session_id: Identifier
    recipe_id: Identifier
    state: Literal["starting", "ready", "stopped", "failed"]
    context_tokens: int = Field(gt=0)
    port: int | None = Field(default=None, ge=1024, le=65535)
    started_at: AwareTimestamp
    message: str = Field(default="", max_length=400)
    bytes_done: int = Field(default=0, ge=0)
    bytes_total: int = Field(default=0, ge=0)
    files_done: int = Field(default=0, ge=0)
    files_total: int = Field(default=0, ge=0)


class ChatMessage(FrozenModel):
    role: Literal["user", "assistant"]
    content: NonEmptyStr


class RecipeChatRequest(FrozenModel):
    session_id: Identifier
    messages: tuple[ChatMessage, ...] = Field(min_length=1, max_length=16)
    max_tokens: int = Field(default=128, ge=1, le=512)
