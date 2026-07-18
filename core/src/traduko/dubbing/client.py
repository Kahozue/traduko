"""Client side of the engine runner: spawns runner.py inside the engine
venv and exchanges JSON lines. The transport is injectable so stage and
service tests never spawn a process."""
from __future__ import annotations

import json
import subprocess
from importlib.resources import files
from pathlib import Path


class DubbingError(Exception):
    pass


def runner_path() -> Path:
    return Path(str(files("traduko.dubbing") / "runner.py"))


def venv_python(engine_dir: Path) -> Path:
    return engine_dir / "venv" / "bin" / "python"


class _SubprocessTransport:
    def __init__(self, python: Path, runner: Path) -> None:
        self.python = python
        self.runner = runner
        self.process: subprocess.Popen | None = None

    def _ensure(self) -> subprocess.Popen:
        if self.process is None or self.process.poll() is not None:
            if not self.python.exists():
                raise DubbingError(
                    f"engine venv python not found: {self.python}; "
                    "install the dubbing engine in settings first"
                )
            self.process = subprocess.Popen(
                [str(self.python), str(self.runner)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            )
        return self.process

    def request(self, payload: dict) -> dict:
        process = self._ensure()
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise DubbingError(f"engine process is not accepting requests: {error}")
        line = process.stdout.readline()
        if not line.strip():
            raise DubbingError("engine process exited without answering")
        try:
            return json.loads(line)
        except ValueError as error:
            raise DubbingError(f"bad engine response: {error}")

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.process = None


class DubbingEngineClient:
    def __init__(
        self,
        engine_dir: Path,
        hf_token: str = "",
        transport=None,
        python: Path | None = None,
        runner: Path | None = None,
    ) -> None:
        self.hf_token = hf_token
        self._transport = transport or _SubprocessTransport(
            python or venv_python(engine_dir), runner or runner_path()
        )

    def _request(self, payload: dict) -> dict:
        response = self._transport.request(payload)
        if not response.get("ok"):
            raise DubbingError(response.get("error", "engine request failed"))
        return response

    def ping(self) -> dict:
        return self._request({"op": "ping"})

    def diarize(self, audio: Path) -> list[dict]:
        response = self._request(
            {"op": "diarize", "audio": str(audio), "hf_token": self.hf_token}
        )
        return response["segments"]

    def synthesize(
        self,
        text: str,
        out: Path,
        prompt_wav: Path | None = None,
        prompt_text: str | None = None,
        instruction: str | None = None,
    ) -> dict:
        payload: dict = {"op": "synthesize", "text": text, "out": str(out)}
        if prompt_wav is not None:
            payload["prompt_wav"] = str(prompt_wav)
        if prompt_text:
            payload["prompt_text"] = prompt_text
        if instruction:
            payload["instruction"] = instruction
        return self._request(payload)

    def close(self) -> None:
        self._transport.close()
