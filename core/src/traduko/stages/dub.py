"""Dubbing pipeline stages: diarize, tts_synthesize, align_duration,
mix_audio, mux. The heavy engine work happens in the managed venv via
DubbingEngineClient; ffmpeg work funnels through media.py builders.
"""
from __future__ import annotations

from pathlib import Path

from ..config import CoreConfig, load_config
from ..dubbing import setup as dubsetup
from ..dubbing.client import DubbingEngineClient, DubbingError
from ..dubbing.models import Speaker, SpeakerAssignment, SpeakersDoc
from ..media import MediaError, build_extract_audio_cmd, ffmpeg_available
from ..media import run as run_media
from . import registry
from .base import StageContext, StageError, StageResult


def _make_client(data_root: Path, config: CoreConfig) -> DubbingEngineClient:
    return DubbingEngineClient(
        dubsetup.engine_dir(data_root), hf_token=config.dubbing.hf_token
    )


def _require_engine(data_root: Path) -> None:
    target = dubsetup.engine_dir(data_root)
    venv_python = target / "venv" / "bin" / "python"
    if not (venv_python.exists() and (target / ".installed").exists()):
        raise StageError(
            "dubbing engine is not installed; install it from the settings video tab"
        )


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def build_speakers_doc(segments: list[dict], turns: list[dict]) -> SpeakersDoc:
    """Assign each subtitle segment the diarization speaker with the most
    overlap (nearest turn when none overlaps; single speaker when
    diarization found nothing), then pick each speaker's longest segment
    as the voice-clone reference."""
    raw: list[tuple[dict, str]] = []
    for seg in segments:
        best, best_overlap = None, 0.0
        for turn in turns:
            overlap = _overlap(seg["start"], seg["end"], turn["start"], turn["end"])
            if overlap > best_overlap:
                best, best_overlap = turn["speaker"], overlap
        if best is None and turns:
            mid = (seg["start"] + seg["end"]) / 2
            nearest = min(
                turns,
                key=lambda t: min(abs(mid - t["start"]), abs(mid - t["end"])),
            )
            best = nearest["speaker"]
        raw.append((seg, best or ""))

    mapping: dict[str, str] = {}
    for _, label in raw:
        if label not in mapping:
            mapping[label] = f"S{len(mapping) + 1}"

    speakers: list[Speaker] = []
    for label, speaker_id in mapping.items():
        own = [seg for seg, l in raw if l == label]
        ref = max(own, key=lambda s: s["end"] - s["start"])
        speakers.append(
            Speaker(
                id=speaker_id,
                label=f"Speaker {speaker_id[1:]}",
                ref_start=ref["start"],
                ref_end=ref["end"],
                ref_text=ref.get("source", ""),
            )
        )
    assignments = [
        SpeakerAssignment(id=seg["id"], speaker=mapping[label]) for seg, label in raw
    ]
    return SpeakersDoc(speakers=speakers, segments=assignments)


@registry.register
class DiarizeStage:
    type = "diarize"

    def run(self, ctx: StageContext) -> StageResult:
        try:
            data = ctx.artifacts.read_latest_json("translation.json")
        except FileNotFoundError as error:
            raise StageError("diarize stage requires a translation artifact") from error
        _require_engine(ctx.data_root)
        config = load_config(ctx.data_root)
        if not config.dubbing.hf_token:
            raise StageError(
                "diarization needs a Hugging Face token for the pyannote model; "
                "set it in the settings video tab"
            )
        try:
            audio_path = ctx.artifacts.latest_path("audio.wav")
        except FileNotFoundError:
            if not ffmpeg_available():
                raise StageError("ffmpeg/ffprobe not found on PATH")
            audio_path = ctx.artifacts.path_for(ctx.stage_index + 1, "audio.wav")
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                run_media(build_extract_audio_cmd(Path(ctx.task.input_path), audio_path))
            except MediaError as error:
                raise StageError(str(error)) from error

        client = _make_client(ctx.data_root, config)
        try:
            turns = client.diarize(audio_path)
        except DubbingError as error:
            raise StageError(str(error)) from error
        finally:
            client.close()

        doc = build_speakers_doc(data["segments"], turns)
        path = ctx.artifacts.write_json(
            ctx.stage_index + 1, "speakers.json", doc.model_dump()
        )
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[path.name])
