"""lab_adapters public surface."""

from .base import AdapterRegistry, InferenceAdapter, ValidatedEvidence, registry
from .llamacpp.adapter import LlamaCppAdapter
from .mock.adapter import MockFutureAdapter
from .strata.adapter import StrataAdapter

__all__ = [
    "AdapterRegistry",
    "InferenceAdapter",
    "LlamaCppAdapter",
    "MockFutureAdapter",
    "StrataAdapter",
    "ValidatedEvidence",
    "registry",
]
