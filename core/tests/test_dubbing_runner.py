"""The runner executes inside the engine venv; these tests run it as a
subprocess with the core interpreter (stdlib-only ops) and with stubbed
engine packages on PYTHONPATH for the heavy ops."""
import json
import os
import subprocess
import sys
import textwrap
from importlib.resources import files
from pathlib import Path

RUNNER = str(files("traduko.dubbing") / "runner.py")


def run_lines(lines: list[str], env: dict | None = None) -> list[dict]:
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    result = subprocess.run(
        [sys.executable, RUNNER],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def test_ping_reports_versions_without_engine_packages() -> None:
    responses = run_lines([json.dumps({"op": "ping"})])
    assert len(responses) == 1
    ping = responses[0]
    assert ping["ok"] is True
    assert ping["python"] == "%d.%d.%d" % sys.version_info[:3]
    # The core venv has no torch/voxcpm/pyannote; ping must not crash.
    assert ping["voxcpm"] is None
    assert ping["pyannote"] is None
    assert ping["mps"] is False


def test_unknown_op_and_bad_json_answer_errors_and_keep_serving() -> None:
    responses = run_lines(
        [json.dumps({"op": "nope"}), "{broken", json.dumps({"op": "ping"})]
    )
    assert [r["ok"] for r in responses] == [False, False, True]
    assert "unknown op" in responses[0]["error"]


def test_eof_exits_cleanly() -> None:
    result = subprocess.run(
        [sys.executable, RUNNER], input="", capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0
    assert result.stdout == ""


def write_stubs(stub_dir: Path) -> None:
    pyannote = stub_dir / "pyannote"
    (pyannote / "audio").mkdir(parents=True)
    (pyannote / "__init__.py").write_text("", encoding="utf-8")
    (pyannote / "audio" / "__init__.py").write_text(
        textwrap.dedent(
            """\
            class _Turn:
                def __init__(self, start, end):
                    self.start = start
                    self.end = end

            class _Diarization:
                def itertracks(self, yield_label=False):
                    yield _Turn(0.0, 1.5), None, "SPEAKER_00"
                    yield _Turn(2.0, 3.0), None, "SPEAKER_01"

            class Pipeline:
                token = None

                @classmethod
                def from_pretrained(cls, name, token=None):
                    cls.token = token
                    return cls()

                def __call__(self, audio):
                    return _Diarization()
            """
        ),
        encoding="utf-8",
    )
    (stub_dir / "voxcpm.py").write_text(
        textwrap.dedent(
            """\
            class VoxCPM:
                last_kwargs = None

                @classmethod
                def from_pretrained(cls, name):
                    return cls()

                def generate(self, **kwargs):
                    VoxCPM.last_kwargs = kwargs
                    return 16000, [0.0] * 8000
            """
        ),
        encoding="utf-8",
    )
    (stub_dir / "soundfile.py").write_text(
        textwrap.dedent(
            """\
            def write(path, data, rate):
                with open(path, "w") as handle:
                    handle.write(f"{len(data)}@{rate}")
            """
        ),
        encoding="utf-8",
    )


def test_diarize_and_synthesize_with_stubbed_engines(tmp_path: Path) -> None:
    write_stubs(tmp_path)
    out_wav = tmp_path / "seg-1.wav"
    responses = run_lines(
        [
            json.dumps({"op": "diarize", "audio": "a.wav", "hf_token": "tok"}),
            json.dumps(
                {
                    "op": "synthesize",
                    "text": "hello",
                    "prompt_wav": "ref.wav",
                    "prompt_text": "hi there",
                    "instruction": "speak faster",
                    "out": str(out_wav),
                }
            ),
        ],
        env={"PYTHONPATH": str(tmp_path)},
    )
    diarize, synth = responses
    assert diarize["ok"] is True
    assert diarize["segments"] == [
        {"start": 0.0, "end": 1.5, "speaker": "SPEAKER_00"},
        {"start": 2.0, "end": 3.0, "speaker": "SPEAKER_01"},
    ]
    assert synth["ok"] is True
    assert synth["path"] == str(out_wav)
    assert synth["duration"] == 0.5
    assert out_wav.read_text() == "8000@16000"


def test_synthesize_without_prompt_omits_prompt_kwargs(tmp_path: Path) -> None:
    write_stubs(tmp_path)
    out_wav = tmp_path / "plain.wav"
    check = tmp_path / "check.py"
    check.write_text(
        "import json, voxcpm\nprint(json.dumps(voxcpm.VoxCPM.last_kwargs))",
        encoding="utf-8",
    )
    # Run synthesize then dump the kwargs the stub captured, in one process.
    script = tmp_path / "driver.py"
    script.write_text(
        textwrap.dedent(
            f"""\
            import io, json, runpy, sys
            sys.argv = [{RUNNER!r}]
            sys.stdin = io.StringIO(json.dumps({{
                "op": "synthesize", "text": "hello", "out": {str(out_wav)!r}
            }}) + "\\n")
            runpy.run_path({RUNNER!r}, run_name="__main__")
            import voxcpm
            print("KWARGS:" + json.dumps(sorted(voxcpm.VoxCPM.last_kwargs)))
            """
        ),
        encoding="utf-8",
    )
    merged_env = dict(os.environ)
    merged_env["PYTHONPATH"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    kwargs_line = [
        line for line in result.stdout.splitlines() if line.startswith("KWARGS:")
    ][0]
    assert json.loads(kwargs_line.removeprefix("KWARGS:")) == ["text"]
