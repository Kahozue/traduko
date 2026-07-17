import time
from pathlib import Path

from traduko.asrsetup import AsrManager, model_cached, model_dir


def fake_cache_writer(cache_dir: Path):
    def download(model_size: str) -> None:
        snap = model_dir(model_size, cache_dir) / "snapshots" / "abc123"
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "model.bin").write_bytes(b"x" * (2 * 1024 * 1024))

    return download


def wait_state(manager: AsrManager, model: str, state: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    status = manager.status(model)
    while time.monotonic() < deadline:
        status = manager.status(model)
        if status["state"] == state:
            return status
    raise AssertionError(f"timed out waiting for {state}, got {status['state']}")


def test_model_cached_detects_snapshot(tmp_path: Path) -> None:
    assert model_cached("small", tmp_path) is False
    fake_cache_writer(tmp_path)("small")
    assert model_cached("small", tmp_path) is True


def test_manager_download_lifecycle(tmp_path: Path) -> None:
    manager = AsrManager(download=fake_cache_writer(tmp_path), cache_dir=tmp_path)
    status = manager.status("small")
    assert status["cached"] is False
    assert status["state"] == "idle"
    assert manager.start_download("small") is True
    status = wait_state(manager, "small", "done")
    assert status["cached"] is True
    assert status["downloaded_mb"] > 0


def test_manager_rejects_concurrent_download(tmp_path: Path) -> None:
    import threading

    gate = threading.Event()

    def slow_download(model_size: str) -> None:
        assert gate.wait(timeout=5)
        fake_cache_writer(tmp_path)(model_size)

    manager = AsrManager(download=slow_download, cache_dir=tmp_path)
    assert manager.start_download("small") is True
    assert manager.start_download("small") is False
    gate.set()
    wait_state(manager, "small", "done")


def test_manager_reports_download_error(tmp_path: Path) -> None:
    def broken(model_size: str) -> None:
        raise RuntimeError("network down")

    manager = AsrManager(download=broken, cache_dir=tmp_path)
    manager.start_download("small")
    status = wait_state(manager, "small", "error")
    assert "network down" in status["error"]
    # A failed download can be retried.
    assert manager.start_download("small") is True


def test_manager_test_wraps_probe_errors(tmp_path: Path) -> None:
    manager = AsrManager(
        probe=lambda model: {"ok": True, "language": "ja"}, cache_dir=tmp_path
    )
    assert manager.test("small") == {"ok": True, "language": "ja"}

    def broken(model: str) -> dict:
        raise RuntimeError("no gpu")

    manager = AsrManager(probe=broken, cache_dir=tmp_path)
    result = manager.test("small")
    assert result["ok"] is False
    assert "no gpu" in result["error"]
