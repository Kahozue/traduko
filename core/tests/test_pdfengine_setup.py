import threading
import time
from pathlib import Path

from traduko.config import CoreConfig
from traduko.pdfengine.setup import PdfManager, engine_dir, find_python


def probe_from(versions: dict[str, tuple[int, int, int] | None]):
    def probe(candidate: str) -> tuple[int, int, int] | None:
        return versions.get(candidate)

    return probe


def test_find_python_picks_first_compatible_candidate() -> None:
    probe = probe_from({"python3.13": (3, 13, 1), "python3.12": None})
    assert find_python(probe=probe) == "python3.13"


def test_find_python_rejects_out_of_range_versions() -> None:
    probe = probe_from({"python3": (3, 14, 0)})
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


def wait_state(manager: PdfManager, state: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    status = manager.status()
    while time.monotonic() < deadline:
        status = manager.status()
        if status["state"] == state:
            return status
    raise AssertionError(f"timed out waiting for {state}, got {status['state']}")


def test_status_before_install(tmp_path: Path) -> None:
    manager = PdfManager(
        tmp_path,
        installer=fake_installer(),
        probe=probe_from({"python3.12": (3, 12, 3)}),
        cache_dir=tmp_path / "no-cache",
    )
    status = manager.status()
    assert status["python"] == "python3.12"
    assert status["venv"] is False
    assert status["installed"] is False
    assert status["state"] == "idle"
    assert status["installed_mb"] == 0.0


def test_install_lifecycle(tmp_path: Path) -> None:
    record: list = []
    manager = PdfManager(
        tmp_path,
        installer=fake_installer(record),
        probe=probe_from({"python3.12": (3, 12, 3)}),
    )
    assert manager.start_install() is True
    status = wait_state(manager, "done")
    assert status["venv"] is True
    assert status["installed"] is True
    assert status["installed_mb"] > 0
    assert record == [(engine_dir(tmp_path), "python3.12")]


def test_install_without_compatible_python_fails_fast(tmp_path: Path) -> None:
    manager = PdfManager(tmp_path, installer=fake_installer(), probe=probe_from({}))
    assert manager.start_install() is False
    assert manager.status()["state"] == "error"


def test_concurrent_install_rejected(tmp_path: Path) -> None:
    gate = threading.Event()
    manager = PdfManager(
        tmp_path,
        installer=fake_installer(gate=gate),
        probe=probe_from({"python3.12": (3, 12, 3)}),
    )
    assert manager.start_install() is True
    assert manager.start_install() is False
    gate.set()
    wait_state(manager, "done")


def test_installer_error_surfaces_in_status(tmp_path: Path) -> None:
    def broken(target_dir: Path, python: str) -> None:
        raise RuntimeError("pip blew up")

    manager = PdfManager(
        tmp_path, installer=broken, probe=probe_from({"python3.12": (3, 12, 3)})
    )
    assert manager.start_install() is True
    status = wait_state(manager, "error")
    assert "pip blew up" in status["error"]


def test_probe_engine_delegates_and_catches(tmp_path: Path) -> None:
    manager = PdfManager(
        tmp_path,
        installer=fake_installer(),
        probe=probe_from({"python3.12": (3, 12, 3)}),
        engine_probe=lambda target_dir: {"ok": True, "version": "2.9.0"},
    )
    assert manager.test() == {"ok": True, "version": "2.9.0"}

    def exploding(target_dir: Path) -> dict:
        raise RuntimeError("no engine")

    manager = PdfManager(
        tmp_path,
        installer=fake_installer(),
        probe=probe_from({"python3.12": (3, 12, 3)}),
        engine_probe=exploding,
    )
    result = manager.test()
    assert result["ok"] is False
    assert "no engine" in result["error"]


def test_pdf_config_round_trip(tmp_path: Path) -> None:
    from traduko.config import load_config, save_config

    config = CoreConfig()
    config.pdf.python = "/opt/py/bin/python"
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded.pdf.python == "/opt/py/bin/python"


def test_install_runs_warmup_and_counts_cache(tmp_path):
    from traduko.pdfengine.setup import PdfManager

    calls: list[str] = []

    def installer(target_dir, python):
        (target_dir / "venv" / "bin").mkdir(parents=True, exist_ok=True)
        (target_dir / "venv" / "bin" / "python").write_text("", encoding="utf-8")
        (target_dir / ".installed").write_text("{}", encoding="utf-8")
        calls.append("install")

    def warmer(target_dir):
        calls.append("warmup")

    cache = tmp_path / "babeldoc-cache"
    cache.mkdir()
    (cache / "model.onnx").write_bytes(b"x" * (2 * 1024 * 1024))
    manager = PdfManager(
        tmp_path,
        installer=installer,
        probe=lambda candidate: (3, 12, 0),
        warmer=warmer,
        cache_dir=cache,
    )
    assert manager.start_install() is True
    import time

    for _ in range(200):
        if manager.status()["state"] in ("done", "error"):
            break
        time.sleep(0.01)
    status = manager.status()
    assert calls == ["install", "warmup"]
    assert status["state"] == "done"
    assert status["installed"] is True
    assert status["cache_mb"] > 0
    assert status["installed_mb"] >= status["cache_mb"]


def test_warmup_failure_does_not_block_install(tmp_path):
    from traduko.pdfengine.setup import PdfManager

    def installer(target_dir, python):
        (target_dir / "venv" / "bin").mkdir(parents=True, exist_ok=True)
        (target_dir / "venv" / "bin" / "python").write_text("", encoding="utf-8")
        (target_dir / ".installed").write_text("{}", encoding="utf-8")

    def warmer(target_dir):
        raise RuntimeError("warmup exploded")

    manager = PdfManager(
        tmp_path,
        installer=installer,
        probe=lambda candidate: (3, 12, 0),
        warmer=warmer,
        cache_dir=tmp_path / "none",
    )
    manager.start_install()
    import time

    for _ in range(200):
        if manager.status()["state"] in ("done", "error"):
            break
        time.sleep(0.01)
    status = manager.status()
    assert status["installed"] is True
    assert status["state"] == "done"
    assert "warmup" in (status["error"] or "")
