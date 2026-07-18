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
            import os


            class _Inner:
                sample_rate = 48000


            class VoxCPM:
                last_kwargs = None
                last_load_denoiser = None
                tts_model = _Inner()

                @classmethod
                def from_pretrained(cls, name, load_denoiser=True):
                    cls.last_load_denoiser = load_denoiser
                    with open(os.environ.get("VOXCPM_STUB_LOG", "/dev/null"), "a") as f:
                        f.write("load_denoiser=%s\\n" % load_denoiser)
                    return cls()

                def generate(self, **kwargs):
                    VoxCPM.last_kwargs = kwargs
                    if os.environ.get("VOXCPM_STUB_RAW"):
                        # Real VoxCPM returns a bare array; the rate lives on
                        # the inner tts_model.
                        return [0.0] * 9600
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


def test_synthesize_reads_rate_from_inner_tts_model(tmp_path: Path) -> None:
    # VoxCPM2 returns a bare array and keeps 48000 on model.tts_model; the
    # old fallback wrote such audio at 16000 (three times slower).
    write_stubs(tmp_path)
    out_wav = tmp_path / "raw.wav"
    responses = run_lines(
        [json.dumps({"op": "synthesize", "text": "hello", "out": str(out_wav)})],
        env={"PYTHONPATH": str(tmp_path), "VOXCPM_STUB_RAW": "1"},
    )
    synth = responses[0]
    assert synth["ok"] is True
    assert synth["duration"] == 0.2
    assert out_wav.read_text() == "9600@48000"


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


def write_torch_stub(stub_dir: Path) -> None:
    (stub_dir / "torch.py").write_text(
        textwrap.dedent(
            """\
            import os

            def manual_seed(seed):
                with open(os.environ.get("TORCH_STUB_LOG", "/dev/null"), "a") as f:
                    f.write(f"seed={seed}\\n")

            class _MPS:
                @staticmethod
                def is_available():
                    return False

            class backends:
                mps = _MPS()
            """
        ),
        encoding="utf-8",
    )


def test_synthesize_forwards_generation_params_and_seed(tmp_path: Path) -> None:
    write_stubs(tmp_path)
    write_torch_stub(tmp_path)
    torch_log = tmp_path / "torch.log"
    out_wav = tmp_path / "seg-2.wav"
    responses = run_lines(
        [
            json.dumps(
                {
                    "op": "synthesize",
                    "text": "hello",
                    "out": str(out_wav),
                    "cfg_value": 2.5,
                    "inference_timesteps": 24,
                    "seed": 42,
                }
            )
        ],
        env={"PYTHONPATH": str(tmp_path), "TORCH_STUB_LOG": str(torch_log)},
    )
    assert responses[0]["ok"] is True
    assert torch_log.read_text() == "seed=42\n"
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; sys.path.insert(0, sys.argv[1]); "
            "print('ok')",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0


def test_synthesize_denoise_reloads_model_with_denoiser(tmp_path: Path) -> None:
    write_stubs(tmp_path)
    log = tmp_path / "load.log"
    out_a = tmp_path / "a.wav"
    out_b = tmp_path / "b.wav"
    responses = run_lines(
        [
            json.dumps({"op": "synthesize", "text": "x", "out": str(out_a)}),
            json.dumps(
                {"op": "synthesize", "text": "y", "out": str(out_b), "denoise": True}
            ),
        ],
        env={"PYTHONPATH": str(tmp_path), "VOXCPM_STUB_LOG": str(log)},
    )
    assert [r["ok"] for r in responses] == [True, True]
    assert log.read_text().splitlines() == [
        "load_denoiser=False",
        "load_denoiser=True",
    ]


def test_diarize_forwards_num_speakers(tmp_path: Path) -> None:
    write_stubs(tmp_path)
    # Extend the pyannote stub to record call kwargs.
    (tmp_path / "pyannote" / "audio" / "__init__.py").write_text(
        textwrap.dedent(
            """\
            import os


            class _Turn:
                def __init__(self, start, end):
                    self.start = start
                    self.end = end

            class _Diarization:
                def itertracks(self, yield_label=False):
                    yield _Turn(0.0, 1.5), None, "SPEAKER_00"

            class Pipeline:
                @classmethod
                def from_pretrained(cls, name, token=None):
                    return cls()

                def __call__(self, audio, **kwargs):
                    with open(os.environ["PYANNOTE_STUB_LOG"], "a") as f:
                        f.write(repr(kwargs) + "\\n")
                    return _Diarization()
            """
        ),
        encoding="utf-8",
    )
    log = tmp_path / "pyannote.log"
    responses = run_lines(
        [
            json.dumps(
                {
                    "op": "diarize",
                    "audio": "x.wav",
                    "hf_token": "t",
                    "num_speakers": 2,
                }
            )
        ],
        env={"PYTHONPATH": str(tmp_path), "PYANNOTE_STUB_LOG": str(log)},
    )
    assert responses[0]["ok"] is True
    assert "num_speakers" in log.read_text()
