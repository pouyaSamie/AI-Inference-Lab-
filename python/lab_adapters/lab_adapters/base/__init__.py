"""Adapter SDK base package."""

from .protocol import InferenceAdapter
from .registry import AdapterRegistry, registry
from .results import ValidatedEvidence

__all__ = ["AdapterRegistry", "InferenceAdapter", "ValidatedEvidence", "registry"]
