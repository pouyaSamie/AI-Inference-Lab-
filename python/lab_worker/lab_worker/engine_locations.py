"""Bounded, read-only engine location discovery. Never executes a candidate."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import TypedDict


class EngineLocation(TypedDict):
    id: str
    engine_id: str
    label: str
    paths: dict[str, str]
    missing: list[str]
    version: str | None
    build_number: int | None
    version_source: str | None


def _version(executable: Path, engine_id: str) -> tuple[str | None, int | None, str | None]:
    build = executable.parent.parent if executable.parent.name == "bin" else executable.parent

    def read(file: Path) -> str:
        try:
            if file.is_symlink() or file.stat().st_size > 262144:
                return ""
            return file.read_text(errors="replace")
        except OSError:
            return ""

    managed = read(build / "lab-install.json")
    if managed:
        try:
            value = json.loads(managed)
            version = value.get("version")
            if isinstance(version, str) and re.fullmatch(
                r"[vV]?\d+(?:\.\d+){1,3}(?:-[A-Za-z0-9.-]+)?|b\d+", version
            ):
                return version, None, "verified release archive"
        except (ValueError, AttributeError):
            pass
    if engine_id == "llamacpp":
        header = read(build / "src/llama-version.h")
        version_match = re.search(r'LLAMA_VERSION\s+"([^"]+)"', header)
        number = re.search(r"LLAMA_BUILD_NUMBER\s*=\s*(\d+)", read(build / "common/build-info.cpp"))
        if version_match:
            return version_match[1][:80], int(number[1]) if number else None, "build metadata"
    else:
        match = re.search(r"^CMAKE_PROJECT_VERSION:STATIC=([0-9.]+)$", read(build / "CMakeCache.txt"), re.M)
        if match:
            return match[1], None, "build metadata"
    # A versioned folder is only a hint, never presented as verified binary identity.
    match = re.search(r"v?(\d+(?:\.\d+){1,3})", build.name)
    return (match[1], None, "folder name (unverified)") if match else (None, None, None)


def _within(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path.is_relative_to(root) for root in roots)


def discover_engine_locations(roots: tuple[Path, ...]) -> list[EngineLocation]:
    """Find installed executables and adjacent support files, without probing.

    Directory symlinks are not followed recursively. Explicitly selected root
    symlinks and executable symlinks are resolved only within selected roots.
    """
    allowed = tuple(dict.fromkeys(root.expanduser().resolve() for root in roots if root.is_dir()))
    found: list[EngineLocation] = []
    seen: set[Path] = set()
    visited = 0

    def usable(candidate: Path, *, executable: bool = False, interpreter: bool = False) -> Path | None:
        try:
            # Keep a discovered venv entry point intact: resolving its Python
            # symlink would discard the environment or escape to /usr/bin.
            resolved = candidate.absolute() if interpreter else candidate.resolve()
            if interpreter and not (candidate.parent.parent / "pyvenv.cfg").is_file():
                return None
            if not _within(resolved, allowed) or not resolved.is_file():
                return None
            if executable and not os.access(resolved, os.X_OK):
                return None
            return resolved
        except OSError:
            return None

    for root in allowed:
        for current, directories, names in os.walk(root, followlinks=False):
            visited += 1
            depth = len(Path(current).parts) - len(root.parts)
            directories[:] = sorted(
                name
                for name in directories
                if not name.startswith(".")
                and not name.startswith("staging-")
                and name not in {"node_modules", "attic", "__pycache__", "venv", "control"}
                and depth < 10
            )
            if visited > 10_000:
                return found
            for name in sorted(set(names) & {"llama-server", "strata"}):
                executable = usable(Path(current) / name, executable=True)
                if executable is None or executable in seen:
                    continue
                seen.add(executable)
                paths: dict[str, str] = {}
                missing: list[str] = []
                if name == "llama-server":
                    engine_id = "llamacpp"
                    paths.update(llama_server_path=str(executable), llama_lib_dir=str(executable.parent))
                    bench = usable(executable.with_name("llama-bench"), executable=True)
                    if bench:
                        paths["llama_bench_path"] = str(bench)
                    else:
                        missing.append("llama-bench")
                else:
                    engine_id = "strata"
                    paths["strata_path"] = str(executable)
                    # Prefer a version-matching source worktree over a shared source tree.
                    version = executable.parent.name
                    for ancestor in (executable.parent, *executable.parents[1:7]):
                        if not _within(ancestor, allowed):
                            continue
                        for relative in (
                            f"worktrees/{version}/serve/server.py",
                            "serve/server.py",
                            "source/serve/server.py",
                        ):
                            script = usable(ancestor / relative)
                            if script:
                                paths.setdefault("strata_server_script", str(script))
                        for relative in (
                            "platforms/linux/venv/bin/python",
                            ".venv/bin/python",
                            "venv/bin/python",
                            "source/.venv/bin/python",
                            "python/bin/python3",
                        ):
                            interpreter_path = usable(
                                ancestor / relative,
                                executable=True,
                                interpreter=relative != "python/bin/python3",
                            )
                            if interpreter_path:
                                paths.setdefault("strata_python", str(interpreter_path))
                    if "strata_server_script" not in paths:
                        missing.append("Strata server script")
                    if "strata_python" not in paths:
                        missing.append("Strata Python environment")
                relative_path = executable.relative_to(
                    next(item for item in allowed if executable.is_relative_to(item))
                )
                family = "llama.cpp" if engine_id == "llamacpp" else "Strata"
                installed_version, build_number, version_source = _version(executable, engine_id)
                found.append(
                    EngineLocation(
                        id=hashlib.sha256(str(executable).encode()).hexdigest()[:24],
                        engine_id=engine_id,
                        label=f"{family} · {relative_path.parent}",
                        paths=paths,
                        missing=missing,
                        version=installed_version,
                        build_number=build_number,
                        version_source=version_source,
                    )
                )
                if len(found) >= 24:
                    return found
    return found
