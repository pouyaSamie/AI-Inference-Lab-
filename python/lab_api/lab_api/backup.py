"""Offline SQLite backup, verification and restore helpers.

The controller and optimizer use separate SQLite databases. These helpers use
SQLite's online backup API so a backup is transactionally consistent even when a
source database is in WAL mode. They never contact a network service and never
delete an existing database during restore: a replacement first snapshots the
current target as ``*.pre-restore-<timestamp>.sqlite3``.

Restores are deliberately offline operations. The runbook requires controller,
optimizer and worker services to be stopped before a target is replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKUP_SCHEMA = "ai-inference-lab-backup-v1"
_LABEL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CHUNK = 1024 * 1024


class BackupError(RuntimeError):
    """A backup or restore cannot proceed without risking data integrity."""


@dataclass(frozen=True, slots=True)
class BackupRecord:
    label: str
    filename: str
    sha256: str
    size_bytes: int
    user_version: int

    def as_json(self) -> dict[str, object]:
        return {
            "label": self.label,
            "filename": self.filename,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "user_version": self.user_version,
        }


@dataclass(frozen=True, slots=True)
class RestoreResult:
    target: Path
    pre_restore: Path | None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=30.0)


def _integrity_check(connection: sqlite3.Connection) -> None:
    row = connection.execute("PRAGMA integrity_check").fetchone()
    if row is None or row[0] != "ok":
        raise BackupError("SQLite integrity_check did not return ok")


def _copy_database(source: Path, destination: Path) -> BackupRecord:
    if not source.is_file():
        raise BackupError(f"source database does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise BackupError(f"destination already exists: {destination}")
    temporary = destination.with_name(f".{destination.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        with _connect_readonly(source) as source_connection, sqlite3.connect(temporary) as target:
            source_connection.backup(target)
            _integrity_check(target)
            user_version = int(target.execute("PRAGMA user_version").fetchone()[0])
            target.commit()
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    except sqlite3.Error as exc:
        raise BackupError(f"SQLite backup failed for {source.name}: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    return BackupRecord(
        label="",
        filename=destination.name,
        sha256=sha256_file(destination),
        size_bytes=destination.stat().st_size,
        user_version=user_version,
    )


def backup_database(source: Path, destination: Path) -> BackupRecord:
    """Write a consistent copy of one SQLite database without modifying it."""
    return _copy_database(source, destination)


def create_backup(databases: dict[str, Path], output_dir: Path) -> dict[str, Any]:
    """Back up labeled SQLite databases and write a verified manifest.

    ``output_dir`` must not already exist. The manifest intentionally records
    only basenames, never absolute source paths, tokens or environment values.
    """
    if not databases:
        raise BackupError("at least one database is required")
    for label in databases:
        if not _LABEL.fullmatch(label):
            raise BackupError(f"invalid database label: {label!r}")
    if output_dir.exists():
        raise BackupError(f"backup destination already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    records: list[BackupRecord] = []
    try:
        for label, source in sorted(databases.items()):
            copied = _copy_database(source, output_dir / f"{label}.sqlite3")
            records.append(
                BackupRecord(
                    label=label,
                    filename=copied.filename,
                    sha256=copied.sha256,
                    size_bytes=copied.size_bytes,
                    user_version=copied.user_version,
                )
            )
        manifest: dict[str, Any] = {
            "schema": BACKUP_SCHEMA,
            "created_at": _now(),
            "databases": [record.as_json() for record in records],
        }
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(manifest_path, 0o600)
        verify_backup(output_dir)
        return manifest
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def verify_backup(output_dir: Path) -> dict[str, Any]:
    """Verify manifest schema, filenames, sizes and SHA-256 digests."""
    manifest_path = output_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError(f"backup manifest is missing or invalid: {manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != BACKUP_SCHEMA:
        raise BackupError("unsupported backup manifest schema")
    databases = manifest.get("databases")
    if not isinstance(databases, list) or not databases:
        raise BackupError("backup manifest has no databases")
    seen: set[str] = set()
    for item in databases:
        if not isinstance(item, dict):
            raise BackupError("backup manifest database entry is invalid")
        label = item.get("label")
        filename = item.get("filename")
        digest = item.get("sha256")
        size = item.get("size_bytes")
        if not isinstance(label, str) or not _LABEL.fullmatch(label) or label in seen:
            raise BackupError("backup manifest contains an invalid or duplicate label")
        seen.add(label)
        if not isinstance(filename, str) or Path(filename).name != filename or filename in ("", ".", ".."):
            raise BackupError(f"backup manifest contains an unsafe filename for {label}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BackupError(f"backup manifest contains an invalid digest for {label}")
        if not isinstance(size, int) or size < 0:
            raise BackupError(f"backup manifest contains an invalid size for {label}")
        path = output_dir / filename
        if not path.is_file():
            raise BackupError(f"backup file is missing: {filename}")
        if path.stat().st_size != size:
            raise BackupError(f"backup file size mismatch: {filename}")
        if sha256_file(path) != digest:
            raise BackupError(f"backup file digest mismatch: {filename}")
    return manifest


def restore_database(backup_file: Path, target: Path, *, replace: bool = False) -> RestoreResult:
    """Restore one verified backup file to ``target``.

    Existing targets are preserved as a pre-restore snapshot unless ``replace``
    is false, in which case the operation fails. Active WAL sidecars are always
    rejected because replacing a database under a running service is unsafe.
    """
    if not backup_file.is_file():
        raise BackupError(f"backup file does not exist: {backup_file}")
    if target.exists() and not replace:
        raise BackupError(f"target already exists; pass replace=True to preserve and replace: {target}")
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{target}{suffix}")
        if sidecar.exists():
            raise BackupError(
                f"target has an active SQLite {suffix} sidecar; stop services and checkpoint first"
            )
    pre_restore: Path | None = None
    if target.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        pre_restore = target.with_name(f"{target.name}.pre-restore-{stamp}.sqlite3")
        _copy_database(target, pre_restore)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.restore-tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        with _connect_readonly(backup_file) as source, sqlite3.connect(temporary) as destination:
            source.backup(destination)
            _integrity_check(destination)
            destination.commit()
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    except sqlite3.Error as exc:
        raise BackupError(f"SQLite restore failed for {target.name}: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
    return RestoreResult(target=target, pre_restore=pre_restore)
