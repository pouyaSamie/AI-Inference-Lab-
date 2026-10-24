"""Engine folder discovery is bounded, read-only and never launches a build."""

from __future__ import annotations

import sys
from pathlib import Path

from lab_worker.engine_locations import discover_engine_locations


def executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 99\n")
    path.chmod(0o755)
    return path


def test_find_build_and_support_files_without_execution(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("Location discovery must not start processes")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    root = tmp_path / "engines"
    server = executable(root / "llama-cpp/builds/linux/current/bin/llama-server")
    bench = executable(server.with_name("llama-bench"))
    (root / "llama-cpp/latest").symlink_to(server.parent, target_is_directory=True)
    before = server.read_bytes()
    found = discover_engine_locations((root,))
    assert len(found) == 1
    assert found[0]["paths"] == {
        "llama_server_path": str(server),
        "llama_bench_path": str(bench),
        "llama_lib_dir": str(server.parent),
    }
    assert found[0]["missing"] == []
    assert server.read_bytes() == before
    assert discover_engine_locations((root,))[0]["id"] == found[0]["id"]


def test_strata_discovers_versioned_source_and_preserves_venv_entrypoint(tmp_path: Path) -> None:
    root = tmp_path / "engines"
    executable(root / "strata/builds/linux/v1/strata")
    source = root / "strata/worktrees/v1/serve/server.py"
    source.parent.mkdir(parents=True)
    source.write_text("# source, never executed\n")
    venv = root / "strata/platforms/linux/venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("# existing environment\n")
    python = venv / "bin/python"
    python.symlink_to(sys.executable)
    found = discover_engine_locations((root,))
    assert found[0]["paths"]["strata_server_script"] == str(source)
    assert found[0]["paths"]["strata_python"] == str(python)
    assert found[0]["missing"] == []


def test_unrelated_files_and_escaping_executable_links_are_not_candidates(tmp_path: Path) -> None:
    root = tmp_path / "engines"
    root.mkdir()
    external = executable(tmp_path / "external/llama-server")
    (root / "llama-server").symlink_to(external)
    (root / "server.py").write_text("not an engine executable\n")
    assert discover_engine_locations((root,)) == []


def test_version_metadata_comes_from_build_not_alias_name(tmp_path: Path) -> None:
    root = tmp_path / "engines"
    server = executable(root / "llama/builds/linux/latest/bin/llama-server")
    executable(server.with_name("llama-bench"))
    build = server.parent.parent
    (build / "src").mkdir()
    (build / "src/llama-version.h").write_text('#define LLAMA_VERSION "0.7.0-dev"\n')
    (build / "common").mkdir()
    (build / "common/build-info.cpp").write_text("int LLAMA_BUILD_NUMBER = 701;\n")
    found = discover_engine_locations((root,))
    assert found[0]["version"] == "0.7.0-dev"
    assert found[0]["build_number"] == 701
    assert found[0]["version_source"] == "build metadata"


def test_managed_strata_uses_matching_control_bundle(tmp_path: Path) -> None:
    root = tmp_path / "managed-engines"
    install = root / "strata-123"
    native = executable(install / "engine/native/strata")
    (native.parent / "lab-install.json").write_text('{"version":"0.1.47"}')
    control = install / "control/strata-control"
    script = control / "serve/server.py"
    script.parent.mkdir(parents=True)
    script.write_text("# no execution\n")
    python = executable(control / "python/bin/python3")
    executable(control / "bin/strata")  # CLI wrapper is not a native engine.
    (install / "serve").symlink_to(script.parent, target_is_directory=True)
    (install / "python").symlink_to(python.parent.parent, target_is_directory=True)
    found = discover_engine_locations((root,))
    assert len(found) == 1
    assert found[0]["version"] == "0.1.47"
    assert found[0]["paths"]["strata_python"] == str(python)
    assert found[0]["paths"]["strata_server_script"] == str(script)
