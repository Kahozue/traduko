import json
from pathlib import Path

import pytest

from traduko.dubbing.client import DubbingEngineClient, DubbingError, runner_path


class FakeTransport:
    """Answers each request from a queue; records what was sent."""

    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.closed = False

    def request(self, payload: dict) -> dict:
        self.requests.append(payload)
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


def test_ping_diarize_synthesize_serialize_requests() -> None:
    transport = FakeTransport(
        [
            {"ok": True, "python": "3.11.5"},
            {"ok": True, "segments": [{"start": 0.0, "end": 1.0, "speaker": "S0"}]},
            {"ok": True, "path": "/tmp/out.wav", "duration": 1.2},
        ]
    )
    client = DubbingEngineClient(
        Path("/data/engines/dubbing"), hf_token="tok", transport=transport
    )
    assert client.ping()["python"] == "3.11.5"
    segments = client.diarize(Path("/tmp/a.wav"))
    assert segments[0]["speaker"] == "S0"
    result = client.synthesize(
        "hello",
        out=Path("/tmp/out.wav"),
        prompt_wav=Path("/tmp/ref.wav"),
        prompt_text="hi",
        instruction="speak faster",
    )
    assert result["duration"] == 1.2
    assert transport.requests[0] == {"op": "ping"}
    assert transport.requests[1] == {
        "op": "diarize",
        "audio": "/tmp/a.wav",
        "hf_token": "tok",
    }
    assert transport.requests[2] == {
        "op": "synthesize",
        "text": "hello",
        "out": "/tmp/out.wav",
        "prompt_wav": "/tmp/ref.wav",
        "prompt_text": "hi",
        "instruction": "speak faster",
    }


def test_error_response_raises_dubbing_error() -> None:
    transport = FakeTransport([{"ok": False, "error": "model exploded"}])
    client = DubbingEngineClient(Path("/data"), transport=transport)
    with pytest.raises(DubbingError, match="model exploded"):
        client.ping()


def test_close_closes_transport() -> None:
    transport = FakeTransport([])
    client = DubbingEngineClient(Path("/data"), transport=transport)
    client.close()
    assert transport.closed is True


def test_runner_path_resolves_to_real_file() -> None:
    path = runner_path()
    assert path.name == "runner.py"
    assert "def serve" in path.read_text(encoding="utf-8")


def test_subprocess_transport_round_trip(tmp_path: Path) -> None:
    """Real spawn against the real runner, using the core interpreter as a
    stand-in for the venv python (ping is stdlib-only)."""
    import sys

    client = DubbingEngineClient(tmp_path, python=Path(sys.executable))
    try:
        ping = client.ping()
        assert ping["python"] == "%d.%d.%d" % sys.version_info[:3]
        # A second request reuses the same live process.
        assert client.ping()["ok"] is True
    finally:
        client.close()


def test_spawn_without_venv_raises(tmp_path: Path) -> None:
    client = DubbingEngineClient(tmp_path)
    with pytest.raises(DubbingError, match="engine venv"):
        client.ping()


def test_transport_detects_dead_process(tmp_path: Path) -> None:
    """A runner that exits mid-conversation surfaces as DubbingError, not a
    hang or an empty-line crash."""
    fake_runner = tmp_path / "runner.py"
    fake_runner.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    import sys

    client = DubbingEngineClient(
        tmp_path, python=Path(sys.executable), runner=fake_runner
    )
    with pytest.raises(DubbingError):
        client.ping()
    client.close()
