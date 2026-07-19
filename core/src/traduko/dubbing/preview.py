"""macOS ``say`` preview synthesis: the quick-preview voice mode. Not a
dubbing engine — deterministic, instant, zero-setup audio so users can
check timing and translation before committing to a real VoxCPM run."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..media import MediaError, probe_duration
from .client import DubbingError

# First-pass synthesis always uses this explicit rate (words per minute)
# so the align stage can rescale it deterministically from the measured
# duration; capped on regen to keep the result intelligible.
PREVIEW_BASE_RATE = 180
PREVIEW_MAX_RATE = 350

# `say -v ?` lines look like "Bad News            en_US    # comment";
# names may contain single spaces, the locale column follows 2+ spaces.
_VOICE_LINE = re.compile(r"^(.+?)\s{2,}(\S+)\s+#")


@dataclass
class SayVoice:
    name: str
    locale: str


def say_available() -> bool:
    return sys.platform == "darwin" and shutil.which("say") is not None


def _run(cmd: list[str], *, input_text: str | None = None):
    return subprocess.run(cmd, input=input_text, capture_output=True, text=True)


def list_voices(runner=_run) -> list[SayVoice]:
    result = runner(["say", "-v", "?"])
    if result.returncode != 0:
        raise DubbingError(f"say -v ? failed: {(result.stderr or '').strip()}")
    voices: list[SayVoice] = []
    for line in result.stdout.splitlines():
        match = _VOICE_LINE.match(line)
        if match:
            voices.append(SayVoice(name=match.group(1).strip(), locale=match.group(2)))
    return voices


def _norm(code: str) -> str:
    return code.strip().lower().replace("-", "_")


# The classic per-language system voices, preferred over the multilingual
# novelty set (whose listing names carry a parenthesized locale, e.g.
# "Eddy (中文（台灣）)") and over plain-named English novelty voices.
PREFERRED_VOICES = frozenset(
    {
        "Meijia", "Mei-Jia", "美佳", "Tingting", "Ting-Ting", "婷婷",
        "Sin-ji", "善怡", "Kyoko", "Otoya", "Yuna", "Samantha", "Alex",
        "Daniel", "Karen", "Anna", "Thomas", "Amelie", "Amélie", "Alice",
        "Monica", "Paulina", "Luciana", "Milena", "Kanya", "Linh",
    }
)


def _voice_rank(voice: SayVoice) -> int:
    if voice.name in PREFERRED_VOICES:
        return 0
    return 2 if "(" in voice.name else 1


def pick_voice(voices: list[SayVoice], language: str | None) -> str | None:
    """Best voice for the language: exact locale beats primary-subtag
    match, classic voices beat novelty ones; None means: let say use the
    system voice."""
    if not language:
        return None
    want = _norm(language)
    primary = want.split("_")[0]
    exact = [v for v in voices if _norm(v.locale) == want]
    prefix = [v for v in voices if _norm(v.locale).split("_")[0] == primary]
    for pool in (exact, prefix):
        if pool:
            return min(pool, key=_voice_rank).name
    return None


def fit_rate(window: float, duration: float, base: int = PREVIEW_BASE_RATE) -> int:
    """Rate that squeezes a clip measuring ``duration`` (synthesized at
    ``base``) into ``window``, with a small safety margin."""
    if window <= 0 or duration <= 0:
        return base
    rate = round(base * duration * 1.02 / window)
    return max(base, min(rate, PREVIEW_MAX_RATE))


def synthesize_preview(
    text: str,
    out: Path,
    voice: str | None = None,
    rate: int = PREVIEW_BASE_RATE,
    runner=_run,
) -> float:
    """Synthesize ``text`` to an AIFF at ``out`` and return its duration.
    Text goes over stdin so quoting and argv length never matter."""
    cmd = ["say", "-o", str(out)]
    if voice:
        cmd += ["-v", voice]
    cmd += ["-r", str(int(rate))]
    result = runner(cmd, input_text=text)
    if result.returncode != 0:
        raise DubbingError(f"say synthesis failed: {(result.stderr or '').strip()}")
    if not out.exists():
        raise DubbingError(f"say produced no output: {out}")
    try:
        return probe_duration(out)
    except MediaError as error:
        raise DubbingError(str(error)) from error
