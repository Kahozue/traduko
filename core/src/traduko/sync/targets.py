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


_DAV = "{DAV:}"


class WebDAVTarget:
    """Minimal WebDAV client: PROPFIND (depth 1, walked per directory so
    servers that forbid depth infinity still work), GET, PUT and MKCOL.
    Basic auth only."""

    def __init__(
        self,
        url: str,
        username: str = "",
        password: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = url.rstrip("/")
        self._base_path = urlsplit(self._base_url).path
        auth = (username, password) if username else None
        self._client = httpx.Client(auth=auth, transport=transport, timeout=30.0)

    def _url(self, rel: str) -> str:
        if not rel:
            return self._base_url
        return f"{self._base_url}/{quote(rel)}"

    def _request(
        self, method: str, rel: str, *, ok: tuple[int, ...], **kwargs
    ) -> httpx.Response:
        try:
            response = self._client.request(method, self._url(rel), **kwargs)
        except httpx.HTTPError as error:
            raise SyncTargetError(f"{method} {rel or '/'} failed: {error}") from error
        if response.status_code not in ok:
            raise SyncTargetError(
                f"{method} {rel or '/'} returned {response.status_code}"
            )
        return response

    def _rel_from_href(self, href: str) -> str:
        path = unquote(urlsplit(href).path)
        if path.startswith(self._base_path):
            path = path[len(self._base_path):]
        return path.strip("/")

    def _list_dir(self, rel: str) -> tuple[list[str], dict[str, float]]:
        response = self._request(
            "PROPFIND", rel, ok=(207,), headers={"Depth": "1"}
        )
        dirs: list[str] = []
        files: dict[str, float] = {}
        root = ElementTree.fromstring(response.content)
        for entry in root.findall(f"{_DAV}response"):
            href = entry.findtext(f"{_DAV}href") or ""
            entry_rel = self._rel_from_href(href)
            if entry_rel == rel:
                continue
            is_collection = (
                entry.find(f".//{_DAV}resourcetype/{_DAV}collection") is not None
            )
            if is_collection:
                dirs.append(entry_rel)
                continue
            modified = entry.findtext(f".//{_DAV}getlastmodified") or ""
            try:
                mtime = parsedate_to_datetime(modified).timestamp()
            except (TypeError, ValueError):
                mtime = 0.0
            files[entry_rel] = mtime
        return dirs, files

    def list_files(self) -> dict[str, float]:
        try:
            pending = [""]
            files: dict[str, float] = {}
            while pending:
                dirs, found = self._list_dir(pending.pop())
                files.update(found)
                pending.extend(dirs)
            return files
        except SyncTargetError:
            # A base collection that does not exist yet is an empty target,
            # not an error; write() creates it on first push.
            probe = self._client.request(
                "PROPFIND", self._url(""), headers={"Depth": "0"}
            )
            if probe.status_code == 404:
                return {}
            raise

    def read(self, rel: str) -> bytes:
        return self._request("GET", rel, ok=(200,)).content

    def write(self, rel: str, data: bytes) -> None:
        parents = list(PurePosixPath(rel).parents)[:-1]
        for parent in reversed(parents):
            # 405 means the collection already exists.
            self._request("MKCOL", str(parent), ok=(200, 201, 405))
        self._request("PUT", rel, ok=(200, 201, 204), content=data)
