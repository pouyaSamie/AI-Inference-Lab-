"""Small parsers shared by pure adapters. No I/O."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from typing import Any

from lab_core import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityProvenance,
    CommandSpec,
    ImpactClass,
    ReadinessKind,
    ReadinessPredicate,
    RegisteredBinary,
    UnsupportedCapabilityError,
)

_LONG_FLAG = re.compile(r"--[a-z0-9][a-z0-9-]*")


def observed_flags(help_text: str) -> frozenset[str]:
    """Extract long flag names observed in an installed binary's help output."""
    return frozenset(_LONG_FLAG.findall(help_text))


def flag_aliases(help_text: str) -> dict[str, frozenset[str]]:
    """Map every observed long flag line to its aliases (best-effort, read-only)."""
    aliases: dict[str, frozenset[str]] = {}
    for line in help_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        names = frozenset(_LONG_FLAG.findall(stripped))
        for name in names:
            aliases[name] = names
    return aliases


def descriptor(
    key: str,
    kind: CapabilityKind,
    *,
    legal_values: Sequence[str | int | float | bool | None] = (),
    minimum: float | None = None,
    maximum: float | None = None,
    step: float | None = None,
    default: str | int | float | bool | None = None,
    constraints: Sequence[str] = (),
    incompatibilities: Sequence[str] = (),
    impact: ImpactClass = ImpactClass.P2,
    restart_required: bool = False,
    quality_risk: bool = False,
    provenance: CapabilityProvenance = CapabilityProvenance.OBSERVED_CLI,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        key=key,
        kind=kind,
        legal_values=tuple(legal_values),
        minimum=minimum,
        maximum=maximum,
        step=step,
        default=default,
        constraints=tuple(constraints),
        incompatibilities=tuple(incompatibilities),
        impact_class=impact,
        restart_required=restart_required,
        quality_risk=quality_risk,
        provenance=provenance,
    )


def require_flags(observed: Iterable[str], required: Sequence[str]) -> None:
    missing = sorted(set(required) - set(observed))
    if missing:
        raise UnsupportedCapabilityError(
            f"installed engine does not expose required flags: {missing}",
            details={"missing_flags": missing},
        )


def unsupported_flags(observed: Iterable[str], required: Sequence[str]) -> list[str]:
    return sorted(set(required) - set(observed))


def probe_command(
    binary: RegisteredBinary, args: Sequence[str], schema: str, timeout: int = 30
) -> CommandSpec:
    return CommandSpec(
        executable_id=binary.executable_id,
        executable_sha256=binary.sha256,
        argv=tuple(args),
        env={"LC_ALL": "C", "LANG": "C"},
        cwd="/",
        timeout_seconds=timeout,
        stdout_schema=schema,
    )


def server_readiness(path: str = "/health", timeout: int = 120) -> ReadinessPredicate:
    return ReadinessPredicate(
        kind=ReadinessKind.HTTP,
        target=f"http://127.0.0.1:{'{port}'}{path}",
        timeout_seconds=timeout,
        interval_ms=250,
        expected_status=200,
    )


def parse_json_document(text: str) -> Any:
    """Parse JSON that may be preceded by engine diagnostic lines."""
    candidate = text.strip()
    if not candidate:
        raise ValueError("evidence is empty")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        for opener in ("[", "{"):
            index = candidate.find(opener)
            if index >= 0:
                try:
                    return json.loads(candidate[index:])
                except json.JSONDecodeError:
                    continue
        raise
