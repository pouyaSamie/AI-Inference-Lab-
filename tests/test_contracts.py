"""Contract generation and stale-artifact checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.contract
def test_committed_contracts_are_current() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_contracts.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.contract
def test_openapi_is_deterministic_and_offline() -> None:
    first = subprocess.run(
        [sys.executable, "scripts/export_openapi.py", "--output", "/tmp/opencode/openapi-a.json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    second = subprocess.run(
        [sys.executable, "scripts/export_openapi.py", "--output", "/tmp/opencode/openapi-b.json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert first.returncode == second.returncode == 0
    a = Path("/tmp/opencode/openapi-a.json").read_text(encoding="utf-8")
    b = Path("/tmp/opencode/openapi-b.json").read_text(encoding="utf-8")
    assert a == b
    document = json.loads(a)
    assert "/api/v1/experiments/plan" in document["paths"]
    assert "PlanRequest" in document["components"]["schemas"]
