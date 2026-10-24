#!/usr/bin/env python3
"""Stage a relocatable CPython + hash-locked dependencies, never a dev venv.

Requires the pinned uv-managed interpreter to be installed on the build host.
Dependency resolution is offline by default; packaging never downloads engines.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = "3.13.16"
PACKAGES = ("lab_core", "lab_bench", "lab_adapters", "lab_updates", "lab_api", "lab_optimizer", "lab_worker")


def run(args: list[str]) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if ROOT / "apps/desktop/release" not in output.parents:
        parser.error("output must be below apps/desktop/release")
    if platform.python_version() != PIN or sys.prefix == sys.base_prefix:
        parser.error(f"build using the workspace venv with pinned CPython {PIN}")
    base = Path(sys.base_prefix)
    if not base.name.startswith(f"cpython-{PIN}-") or not (base / "bin/python3").exists():
        parser.error("a relocatable uv-managed CPython distribution is required")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    shutil.copytree(
        base, output / "python", symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    requirements = output / "requirements.txt"
    run(
        [
            "uv",
            "export",
            "--frozen",
            "--all-packages",
            "--no-dev",
            "--no-emit-workspace",
            "--quiet",
            "--output-file",
            str(requirements),
        ]
    )
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(output / "python/bin/python3"),
            "--target",
            str(output / "site-packages"),
            "--require-hashes",
            "--no-deps",
            "--no-python-downloads",
            "--link-mode=copy",
            *([] if args.allow_network else ["--offline"]),
            "-r",
            str(requirements),
        ]
    )
    for name in PACKAGES:
        shutil.copytree(
            ROOT / "python" / name / name,
            output / "packages" / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    shutil.copytree(
        ROOT / "python/lab_api/migrations",
        output / "migrations",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    # The explicit simulator must use the same frozen CLI facts outside a checkout.
    fixture = Path("fixtures/engines/llamacpp-0.7.0-dev-build701")
    shutil.copytree(ROOT / fixture, output / fixture)
    shutil.copyfile(ROOT / "apps/desktop/runtime/bootstrap.py", output / "bootstrap.py")
    manifest = {
        "python": PIN,
        "platform": platform.machine(),
        "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
    }
    manifest["python_executable_sha256"] = hashlib.sha256(
        (output / "python/bin/python3").read_bytes()
    ).hexdigest()
    manifest["requirements_sha256"] = hashlib.sha256(requirements.read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # Verify the staged interpreter and all seven imports without using the checkout.
    probe = "import sys; sys.path[:0]=sys.argv[1:]; " + "; ".join(f"import {name}" for name in PACKAGES)
    run(
        [
            str(output / "python/bin/python3"),
            "-I",
            "-c",
            probe,
            str(output / "site-packages"),
            str(output / "packages"),
        ]
    )
    print(f"Staged self-contained backend: {output}")


if __name__ == "__main__":
    main()
