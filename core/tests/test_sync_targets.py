from pathlib import Path

import pytest

from traduko.sync.targets import LocalFolderTarget, SyncTargetError


def test_write_creates_nested_paths_and_reads_back(tmp_path: Path) -> None:
    target = LocalFolderTarget(tmp_path / "remote")
    target.write("prompts/translate.txt", b"hello")
    assert target.read("prompts/translate.txt") == b"hello"
    assert (tmp_path / "remote" / "prompts" / "translate.txt").read_bytes() == b"hello"


def test_list_files_returns_posix_relative_paths_with_mtimes(tmp_path: Path) -> None:
    target = LocalFolderTarget(tmp_path / "remote")
    target.write("config/core.yaml", b"a")
    target.write("tasks/mach-1/p/t1.json", b"b")
    files = target.list_files()
    assert set(files) == {"config/core.yaml", "tasks/mach-1/p/t1.json"}
    assert all(isinstance(mtime, float) for mtime in files.values())


def test_read_missing_file_raises(tmp_path: Path) -> None:
    target = LocalFolderTarget(tmp_path / "remote")
    with pytest.raises(SyncTargetError):
        target.read("nope.txt")


def test_empty_folder_lists_nothing(tmp_path: Path) -> None:
    assert LocalFolderTarget(tmp_path / "remote").list_files() == {}
