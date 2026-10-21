"""Offline backup/restore safety tests for the two SQLite stores."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from lab_api.backup import (
    BackupError,
    create_backup,
    restore_database,
    verify_backup,
)


def _database(path: Path, value: str, *, user_version: int = 7, wal: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA journal_mode={'WAL' if wal else 'DELETE'}")
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample (value) VALUES (?)", (value,))
        connection.execute(f"PRAGMA user_version={user_version}")
        connection.commit()
    return path


def _value(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT value FROM sample").fetchone()
    assert row is not None
    return str(row[0])


def test_backup_verify_and_restore_two_separate_databases(tmp_path: Path) -> None:
    controller = _database(tmp_path / "controller.sqlite3", "controller-data")
    optimizer = _database(tmp_path / "optuna.sqlite3", "optimizer-data", user_version=3)
    backup_dir = tmp_path / "backup"

    manifest = create_backup({"controller": controller, "optimizer": optimizer}, backup_dir)
    assert manifest["schema"] == "ai-inference-lab-backup-v1"
    assert [item["label"] for item in manifest["databases"]] == ["controller", "optimizer"]
    assert {item["user_version"] for item in manifest["databases"]} == {3, 7}
    assert verify_backup(backup_dir) == manifest

    restored = restore_database(backup_dir / "controller.sqlite3", tmp_path / "restored.sqlite3")
    assert restored.pre_restore is None
    assert _value(restored.target) == "controller-data"


def test_backup_verification_detects_tampering(tmp_path: Path) -> None:
    database = _database(tmp_path / "controller.sqlite3", "original")
    backup_dir = tmp_path / "backup"
    create_backup({"controller": database}, backup_dir)

    with (backup_dir / "controller.sqlite3").open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(BackupError, match=r"size mismatch|digest mismatch"):
        verify_backup(backup_dir)


def test_restore_preserves_existing_target_before_replacement(tmp_path: Path) -> None:
    source = _database(tmp_path / "controller.sqlite3", "new")
    backup_dir = tmp_path / "backup"
    create_backup({"controller": source}, backup_dir)
    target = _database(tmp_path / "live.sqlite3", "old", wal=False)

    with pytest.raises(BackupError, match="target already exists"):
        restore_database(backup_dir / "controller.sqlite3", target)

    result = restore_database(backup_dir / "controller.sqlite3", target, replace=True)
    assert result.pre_restore is not None
    assert _value(result.pre_restore) == "old"
    assert _value(target) == "new"


def test_backup_rejects_unsafe_labels_and_active_sidecars(tmp_path: Path) -> None:
    database = _database(tmp_path / "controller.sqlite3", "data")
    with pytest.raises(BackupError, match="invalid database label"):
        create_backup({"../escape": database}, tmp_path / "backup")

    backup_dir = tmp_path / "backup2"
    create_backup({"controller": database}, backup_dir)
    target = tmp_path / "target.sqlite3"
    Path(f"{target}-wal").write_text("stale", encoding="utf-8")
    with pytest.raises(BackupError, match="active SQLite -wal sidecar"):
        restore_database(backup_dir / "controller.sqlite3", target)
