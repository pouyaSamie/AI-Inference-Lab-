"""Release extraction never executes archives or writes outside a new staging root."""

import io
import tarfile
from pathlib import Path

import pytest
from lab_worker.engine_archive import extract_engine_archive


def archive(path: Path, name: str, *, link: str | None = None) -> None:
    with tarfile.open(path, "w:gz") as tar:
        item = tarfile.TarInfo(name)
        if link is not None:
            item.type = tarfile.SYMTYPE
            item.linkname = link
            tar.addfile(item)
        else:
            item.size = 4
            item.mode = 0o4755
            tar.addfile(item, io.BytesIO(b"test"))


def test_extracts_without_running_and_strips_special_permissions(tmp_path: Path) -> None:
    source = tmp_path / "engine.tar.gz"
    archive(source, "bin/llama-server")
    target = tmp_path / "new"
    extract_engine_archive(source, target)
    assert (target / "bin/llama-server").read_bytes() == b"test"
    assert (target / "bin/llama-server").stat().st_mode & 0o7777 == 0o700
    with pytest.raises(ValueError, match="new"):
        extract_engine_archive(source, target)


@pytest.mark.parametrize(
    "name,link", [("../outside", None), ("/outside", None), ("link", "../../outside"), ("link", "/outside")]
)
def test_refuses_path_and_link_escape(tmp_path: Path, name: str, link: str | None) -> None:
    source = tmp_path / "engine.tar.gz"
    archive(source, name, link=link)
    with pytest.raises(ValueError, match="Unsafe"):
        extract_engine_archive(source, tmp_path / "new")
    assert not (tmp_path / "outside").exists()
