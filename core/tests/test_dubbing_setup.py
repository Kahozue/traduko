import threading
import time
from pathlib import Path

from traduko.dubbing.setup import DubbingManager, engine_dir, find_python


def probe_from(versions: dict[str, tuple[int, int, int] | None]):
    def probe(candidate: str) -> tuple[int, int, int] | None:
        return versions.get(candidate)

    return probe


def test_find_python_picks_first_compatible_candidate() -> None:
    probe = probe_from(
        {
            "python3.12": None,
            "python3.11": (3, 11, 5),
            "python3.10": (3, 10, 20),
        }
    )
    assert find_python(probe=probe) == "python3.11"


def test_find_python_rejects_out_of_range_versions() -> None:
    probe = probe_from({"python3": (3, 13, 5)})
    assert find_python(probe=probe) is None


def test_find_python_override_wins_but_must_be_compatible() -> None:
    probe = probe_from({"/opt/py/bin/python": (3, 12, 1), "python3.11": (3, 11, 5)})
    assert find_python("/opt/py/bin/python", probe=probe) == "/opt/py/bin/python"
    assert find_python("/missing", probe=probe) == "python3.11"


def fake_installer(record: list | None = None, gate: threading.Event | None = None):
    def install(target_dir: Path, python: str) -> None:
        if gate is not None:
            assert gate.wait(timeout=5)
        if record is not None:
            record.append((target_dir, python))
        bin_dir = target_dir / "venv" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "python").write_bytes(b"x" * (2 * 1024 * 1024))
        (target_dir / ".installed").write_text("{}", encoding="utf-8")

    return install


def wait_state(manager: DubbingManager, state: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    status = manager.status()
    while time.monotonic() < deadline:
        status = manager.status()
        if status["state"] == state:
            return status
    raise AssertionError(f"timed out waiting for {state}, got {status['state']}")


def test_status_before_install(tmp_path: Path) -> None:
    manager = DubbingManager(
        tmp_path, installer=fake_installer(), probe=probe_from({"python3.11": (3, 11, 5)})
    )
    status = manager.status()
    assert status["python"] == "python3.11"
    assert status["venv"] is False
    assert status["installed"] is False
    assert status["state"] == "idle"
    assert status["installing"] is False
    assert status["installed_mb"] == 0.0


def test_install_lifecycle(tmp_path: Path) -> None:
    record: list = []
    manager = DubbingManager(
        tmp_path,
        installer=fake_installer(record),
        probe=probe_from({"python3.11": (3, 11, 5)}),
    )
    assert manager.start_install() is True
    status = wait_state(manager, "done")
    assert status["venv"] is True
    assert status["installed"] is True
    assert status["installed_mb"] > 0
    assert record == [(engine_dir(tmp_path), "python3.11")]


def test_install_without_compatible_python_fails_fast(tmp_path: Path) -> None:
    manager = DubbingManager(tmp_path, installer=fake_installer(), probe=probe_from({}))
    assert manager.start_install() is False
    status = manager.status()
    assert status["state"] == "error"
    assert "python" in status["error"].lower()


def test_concurrent_install_rejected(tmp_path: Path) -> None:
    gate = threading.Event()
    manager = DubbingManager(
        tmp_path,
        installer=fake_installer(gate=gate),
        probe=probe_from({"python3.11": (3, 11, 5)}),
    )
    assert manager.start_install() is True
    assert manager.start_install() is False
    gate.set()
    wait_state(manager, "done")


def test_installer_error_surfaces_in_status(tmp_path: Path) -> None:
    def broken(target_dir: Path, python: str) -> None:
        raise RuntimeError("pip blew up")

    manager = DubbingManager(
        tmp_path, installer=broken, probe=probe_from({"python3.11": (3, 11, 5)})
    )
    assert manager.start_install() is True
    status = wait_state(manager, "error")
    assert "pip blew up" in status["error"]


def test_probe_engine_delegates_and_catches(tmp_path: Path) -> None:
    manager = DubbingManager(
        tmp_path,
        installer=fake_installer(),
        probe=probe_from({"python3.11": (3, 11, 5)}),
        engine_probe=lambda target_dir: {"ok": True, "torch": "2.5.0"},
    )
    assert manager.test() == {"ok": True, "torch": "2.5.0"}

    def exploding(target_dir: Path) -> dict:
        raise RuntimeError("no engine")

    manager = DubbingManager(
        tmp_path,
        installer=fake_installer(),
        probe=probe_from({"python3.11": (3, 11, 5)}),
        engine_probe=exploding,
    )
    result = manager.test()
    assert result["ok"] is False
    assert "no engine" in result["error"]


def test_model_status_and_download(tmp_path):
    from traduko.dubbing.setup import DubbingManager

    downloads: list[str] = []

    def fake_download(repo: str) -> None:
        downloads.append(repo)

    manager = DubbingManager(
        tmp_path,
        model_downloader=fake_download,
        model_info=lambda repo: 4960.0,
        model_cache_dir=tmp_path / "hf",
    )
    status = manager.model_status()
    assert status["repo"] == "openbmb/VoxCPM2"
    assert status["total_mb"] == 4960.0
    assert status["cached"] is False
    assert status["downloading"] is False

    assert manager.start_model_download() is True
    import time

    for _ in range(100):
        if manager.model_status()["state"] in ("done", "error"):
            break
        time.sleep(0.01)
    assert manager.model_status()["state"] == "done"
    assert downloads == ["openbmb/VoxCPM2"]
    # A second start while idle is allowed; while downloading it would be
    # refused (covered by the state machine reused from AsrManager).


def test_model_cached_detection(tmp_path):
    from traduko.dubbing.setup import DubbingManager

    cache = tmp_path / "hf"
    snapshot = cache / "models--openbmb--VoxCPM2" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    manager = DubbingManager(
        tmp_path,
        model_info=lambda repo: 4960.0,
        model_cache_dir=cache,
    )
    assert manager.model_status()["cached"] is True
    blobs = cache / "models--openbmb--VoxCPM2" / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "x.incomplete").write_text("", encoding="utf-8")
    assert manager.model_status()["cached"] is False


def test_model_info_failure_falls_back_to_known_size(tmp_path):
    from traduko.dubbing.setup import DubbingManager

    def broken_info(repo: str) -> float:
        raise RuntimeError("offline")

    manager = DubbingManager(
        tmp_path, model_info=broken_info, model_cache_dir=tmp_path / "hf"
    )
    assert manager.model_status()["total_mb"] == 4960.0
