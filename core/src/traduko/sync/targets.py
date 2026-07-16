"""Sync targets: the remote side of cloud sync, abstracted as "a folder"
(design doc section 9).

A target only knows relative POSIX paths, bytes and mtimes; every policy
decision (what to sync, who wins) lives in the engine. LocalFolderTarget
covers plain directories and desktop cloud-drive folders; WebDAVTarget is
a minimal client on httpx so no extra dependency is needed.
"""
from __future__ import annotations

import os
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree

import httpx


class SyncTargetError(Exception):
    pass


class SyncTarget(Protocol):
    def list_files(self) -> dict[str, float]:
        """Map of relative POSIX path -> mtime (epoch seconds)."""
        ...

    def read(self, rel: str) -> bytes: ...

    def write(self, rel: str, data: bytes) -> None: ...


class LocalFolderTarget:
    def __init__(self, base: Path) -> None:
        self.base = base

    def list_files(self) -> dict[str, float]:
        if not self.base.exists():
            return {}
        files: dict[str, float] = {}
        for path in self.base.rglob("*"):
            if path.is_file():
                rel = path.relative_to(self.base).as_posix()
                files[rel] = path.stat().st_mtime
        return files

    def read(self, rel: str) -> bytes:
        try:
            return (self.base / rel).read_bytes()
        except OSError as error:
            raise SyncTargetError(f"cannot read {rel}: {error}") from error

    def write(self, rel: str, data: bytes) -> None:
        path = self.base / rel
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError as error:
            raise SyncTargetError(f"cannot write {rel}: {error}") from error
