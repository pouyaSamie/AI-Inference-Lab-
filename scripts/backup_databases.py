#!/usr/bin/env python
"""Operator CLI for offline controller/optimizer SQLite backup and restore."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lab_api.backup import BackupError, create_backup, restore_database, verify_backup


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create, verify or restore consistent offline SQLite backups. "
            "Stop controller/optimizer/worker services before restoring a live database."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup", help="back up labeled SQLite databases")
    backup.add_argument("--controller", type=Path, required=True)
    backup.add_argument("--optimizer", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify", help="verify a backup directory and manifest")
    verify.add_argument("--backup", type=Path, required=True)

    restore = subparsers.add_parser("restore", help="restore one database from a verified backup")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--label", required=True)
    restore.add_argument("--target", type=Path, required=True)
    restore.add_argument("--replace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "backup":
            manifest = create_backup(
                {"controller": args.controller, "optimizer": args.optimizer},
                args.output,
            )
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0
        if args.command == "verify":
            manifest = verify_backup(args.backup)
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0
        manifest = verify_backup(args.backup)
        matches = [
            item
            for item in manifest.get("databases", [])
            if isinstance(item, dict) and item.get("label") == args.label
        ]
        if len(matches) != 1:
            raise BackupError(f"backup does not contain exactly one database labeled {args.label!r}")
        result = restore_database(
            args.backup / str(matches[0]["filename"]),
            args.target,
            replace=args.replace,
        )
        print(
            json.dumps(
                {
                    "target": str(result.target),
                    "pre_restore": str(result.pre_restore) if result.pre_restore else None,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except BackupError as exc:
        print(f"backup error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
