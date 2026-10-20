"""Per-command execution sandboxes."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import time

from lab_core import SandboxPaths

from .config import WorkerSettings

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def create_sandbox(settings: WorkerSettings, command_id: str) -> SandboxPaths:
    stem = _SAFE.sub("-", command_id)[:100] or "command"
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    root = settings.resolved_sandbox_root / f"{stem}-{stamp}-{os.getpid()}"
    work_dir = root / "work"
    log_dir = root / "logs"
    artifact_dir = root / "artifacts"
    temp_home = root / "home"
    for path in (root, work_dir, log_dir, artifact_dir, temp_home):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            path.chmod(0o700)
    return SandboxPaths(
        root=str(root),
        work_dir=str(work_dir),
        log_dir=str(log_dir),
        artifact_dir=str(artifact_dir),
        temp_home=str(temp_home),
    )


def cleanup_sandboxes(settings: WorkerSettings, *, keep: int | None = None) -> int:
    keep = settings.keep_sandboxes if keep is None else keep
    root = settings.resolved_sandbox_root
    if not root.is_dir():
        return 0
    entries = sorted(
        (item for item in root.iterdir() if item.is_dir()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for item in entries[keep:]:
        with contextlib.suppress(OSError):
            shutil.rmtree(item)
            removed += 1
    return removed
