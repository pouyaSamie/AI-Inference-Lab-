"""Trusted adapter registry. No dynamic remote plugin loading in v1."""

from __future__ import annotations

from typing import cast

from lab_core import EngineId

from ..llamacpp.adapter import LlamaCppAdapter
from ..mock.adapter import MockFutureAdapter
from ..strata.adapter import StrataAdapter
from .protocol import InferenceAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[EngineId, InferenceAdapter] = {
            EngineId.LLAMACPP: cast(InferenceAdapter, LlamaCppAdapter()),
            EngineId.STRATA: cast(InferenceAdapter, StrataAdapter()),
            EngineId.MOCK_FUTURE: cast(InferenceAdapter, MockFutureAdapter()),
        }

    def get(self, engine_id: EngineId | str) -> InferenceAdapter:
        try:
            key = EngineId(engine_id)
        except ValueError as exc:
            raise KeyError(f"unknown engine: {engine_id!r}") from exc
        try:
            return self._adapters[key]
        except KeyError as exc:
            raise KeyError(f"no trusted adapter registered for {key.value}") from exc

    def all(self) -> tuple[InferenceAdapter, ...]:
        return tuple(self._adapters.values())

    def production(self) -> tuple[InferenceAdapter, ...]:
        return tuple(adapter for adapter in self._adapters.values() if adapter.adapter_id is not EngineId.MOCK_FUTURE)


_default_registry: AdapterRegistry | None = None


def registry() -> AdapterRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = AdapterRegistry()
    return _default_registry
