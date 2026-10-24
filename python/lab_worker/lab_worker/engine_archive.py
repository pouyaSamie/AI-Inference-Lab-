"""Extract an approved release archive into a new private staging directory only."""

from __future__ import annotations

import json
import os
import tarfile
from pathlib import Path, PurePosixPath


def extract_engine_archive(archive: Path, target: Path) -> None:
    if target.exists():
        raise ValueError("Extraction target must be new")
    with tarfile.open(archive, "r:gz") as bundle:
        members = []
        total = 0
        for member in bundle:
            members.append(member)
            total += member.size
            if len(members) > 20000 or total > 4 * 1024**3:
                raise ValueError("Archive exceeds extraction limits")
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or "\\" in member.name:
                raise ValueError("Unsafe archive path")
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise ValueError("Unsupported archive entry")
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or ".." in link.parts or "\\" in member.linkname:
                    raise ValueError("Unsafe archive link")
            if member.size > 1024**3:
                raise ValueError("Archive entry exceeds size limit")
        target.mkdir(mode=0o700)
        # Python's data filter also rejects escaping links, device nodes and
        # special permissions. Never run a post-install hook from the archive.
        bundle.extractall(target, members=members, filter="data")
    for file in target.rglob("*"):
        if not file.is_symlink() and file.is_file():
            file.chmod(0o700 if os.access(file, os.X_OK) else 0o600)


def main(archive: str, target: str) -> None:
    extract_engine_archive(Path(archive), Path(target))
    print(json.dumps({"extracted": True}))
