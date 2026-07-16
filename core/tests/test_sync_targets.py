from pathlib import Path

import httpx
import pytest

from traduko.sync.targets import LocalFolderTarget, SyncTargetError, WebDAVTarget


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


class FakeDav:
    """Minimal in-memory WebDAV server behind httpx.MockTransport."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.collections: set[str] = {""}
        self.requests: list[httpx.Request] = []

    def _rel(self, request: httpx.Request) -> str:
        return request.url.path.removeprefix("/dav/traduko").strip("/")

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        rel = self._rel(request)
        if request.method == "PROPFIND":
            if rel not in self.collections:
                return httpx.Response(404)
            responses = [self._propfind_entry(rel, collection=True)]
            prefix = f"{rel}/" if rel else ""
            children = {
                path[len(prefix):].split("/")[0]
                for path in set(self.files) | {c for c in self.collections if c}
                if path.startswith(prefix) and path != rel
            }
            for child in sorted(children):
                child_rel = f"{prefix}{child}"
                responses.append(
                    self._propfind_entry(
                        child_rel, collection=child_rel in self.collections
                    )
                )
            body = (
                '<?xml version="1.0"?><D:multistatus xmlns:D="DAV:">'
                + "".join(responses)
                + "</D:multistatus>"
            )
            return httpx.Response(207, text=body)
        if request.method == "GET":
            if rel not in self.files:
                return httpx.Response(404)
            return httpx.Response(200, content=self.files[rel])
        if request.method == "PUT":
            self.files[rel] = request.content
            return httpx.Response(201)
        if request.method == "MKCOL":
            if rel in self.collections:
                return httpx.Response(405)
            self.collections.add(rel)
            return httpx.Response(201)
        return httpx.Response(405)

    def _propfind_entry(self, rel: str, collection: bool) -> str:
        href = "/dav/traduko/" + rel + ("/" if collection and rel else "")
        resourcetype = "<D:collection/>" if collection else ""
        return (
            f"<D:response><D:href>{href}</D:href><D:propstat><D:prop>"
            f"<D:resourcetype>{resourcetype}</D:resourcetype>"
            "<D:getlastmodified>Wed, 15 Jul 2026 10:00:00 GMT</D:getlastmodified>"
            "</D:prop></D:propstat></D:response>"
        )


def make_webdav() -> tuple[FakeDav, WebDAVTarget]:
    dav = FakeDav()
    target = WebDAVTarget(
        "https://host.example/dav/traduko/",
        username="kaho",
        password="secret",
        transport=httpx.MockTransport(dav.handler),
    )
    return dav, target


def test_webdav_round_trip_and_listing() -> None:
    dav, target = make_webdav()
    target.write("prompts/translate.txt", b"hello")
    target.write("config/core.yaml", b"a: 1\n")
    assert target.read("prompts/translate.txt") == b"hello"
    files = target.list_files()
    assert set(files) == {"prompts/translate.txt", "config/core.yaml"}
    assert all(mtime > 0 for mtime in files.values())


def test_webdav_write_creates_parent_collections() -> None:
    dav, target = make_webdav()
    target.write("tasks/mach-1/p/t1.json", b"{}")
    assert "tasks/mach-1/p" in dav.collections
    assert dav.files["tasks/mach-1/p/t1.json"] == b"{}"


def test_webdav_missing_read_and_server_errors_raise() -> None:
    dav, target = make_webdav()
    with pytest.raises(SyncTargetError):
        target.read("nope.txt")

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    broken = WebDAVTarget(
        "https://host.example/dav/traduko/", transport=httpx.MockTransport(boom)
    )
    with pytest.raises(SyncTargetError):
        broken.write("x.txt", b"x")


def test_webdav_sends_basic_auth_and_empty_base_lists_nothing() -> None:
    dav, target = make_webdav()
    assert target.list_files() == {}
    assert dav.requests[0].headers.get("authorization", "").startswith("Basic ")
