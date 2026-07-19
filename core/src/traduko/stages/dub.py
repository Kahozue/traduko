"""Dubbing pipeline stages: diarize, tts_synthesize, align_duration,
mix_audio, mux. The heavy engine work happens in the managed venv via
DubbingEngineClient; ffmpeg work funnels through media.py builders.
"""
from __future__ import annotations

from pathlib import Path

import json

from ..config import CoreConfig, load_config
from ..dubbing import preview
from ..dubbing import setup as dubsetup
from ..dubbing.align import plan_segment
from ..dubbing.client import DubbingEngineClient, DubbingError
from ..dubbing.models import (
    DubManifestDoc,
    DubSegment,
    DubTimelineDoc,
    Speaker,
    SpeakerAssignment,
    SpeakersDoc,
    TimelineSegment,
)
from ..media import (
    MediaError,
    build_atempo_cmd,
    build_extract_audio_cmd,
    build_extract_clip_cmd,
    build_extract_mix_audio_cmd,
    build_mix_cmd,
    build_mix_filter_script,
    build_mux_cmd,
    ffmpeg_available,
)
from ..media import run as run_media
from ..tasks import VOICE_MODES
from . import registry
from .base import StageContext, StageError, StageResult


def _make_client(data_root: Path, config: CoreConfig) -> DubbingEngineClient:
    return DubbingEngineClient(
        dubsetup.engine_dir(data_root), hf_token=config.dubbing.hf_token
    )


def _synth_options(config: CoreConfig, params: dict) -> dict:
    """Generation kwargs for client.synthesize: the settings-page global
    defaults, overridden by same-named stage params."""
    dubbing = config.dubbing
    options = {
        "cfg_value": params.get("cfg_value", dubbing.cfg_value),
        "inference_timesteps": params.get(
            "inference_timesteps", dubbing.inference_timesteps
        ),
        "seed": params.get("seed", dubbing.seed),
        "denoise": bool(params.get("denoise", dubbing.denoise)),
    }
    return options


def _voice_mode(params: dict) -> str:
    """Task-level voice mode: clone the original speakers (default), shape
    a voice from the instruction text, or macOS-say quick preview."""
    mode = params.get("voice_mode") or "clone"
    if mode not in VOICE_MODES:
        raise StageError(
            f"unknown voice_mode: {mode}; expected one of {', '.join(VOICE_MODES)}"
        )
    return mode


def _require_engine(data_root: Path) -> None:
    target = dubsetup.engine_dir(data_root)
    venv_python = target / "venv" / "bin" / "python"
    if not (venv_python.exists() and (target / ".installed").exists()):
        raise StageError(
            "dubbing engine is not installed; install it from the settings video tab"
        )


DUB_TEXT_MODES = ("auto", "translation", "original")


def _dub_text_mode(params: dict) -> str:
    """What the dub stages speak: auto (target when translated, source
    otherwise), translation (target only), or original (source only)."""
    mode = params.get("dub_text") or "auto"
    if mode not in DUB_TEXT_MODES:
        raise StageError(
            f"unknown dub_text: {mode}; expected one of {', '.join(DUB_TEXT_MODES)}"
        )
    return mode


def _normalize_segments_doc(data: dict) -> dict:
    """Common shape for translation/segments/asr docs: the text of an
    untranslated doc lands in source, a translation adds target."""
    segments = []
    for seg in data["segments"]:
        norm = {
            "id": seg["id"],
            "start": seg.get("start", 0.0),
            "end": seg.get("end", 0.0),
            "source": seg.get("source", seg.get("text", "")),
        }
        if "target" in seg:
            norm["target"] = seg["target"]
        if "speaker" in seg:
            norm["speaker"] = seg["speaker"]
        segments.append(norm)
    return {
        "language": data.get("language") or data.get("source_language"),
        "target_language": data.get("target_language"),
        "segments": segments,
    }


def _read_dub_text(ctx: StageContext) -> dict:
    """Segments a dub stage works on, resolved through the fallback chain
    translation.json -> segments.json -> asr.json as dub_text allows."""
    mode = _dub_text_mode(ctx.params)
    names = ["segments.json", "asr.json"]
    if mode == "translation":
        names = ["translation.json"]
    elif mode == "auto":
        names = ["translation.json", *names]
    for name in names:
        try:
            return _normalize_segments_doc(ctx.artifacts.read_latest_json(name))
        except FileNotFoundError:
            continue
    if mode == "translation":
        raise StageError("dub_text=translation requires a translation artifact")
    raise StageError("dub stages require a translation, segments or asr artifact")


def _dub_segment_text(seg: dict, mode: str) -> str:
    source = (seg.get("source") or "").strip()
    if mode == "original":
        return source
    target = (seg.get("target") or "").strip()
    return target if mode == "translation" else (target or source)


def _dub_voice_language(doc: dict, mode: str) -> str | None:
    if mode == "original":
        return doc.get("language")
    return doc.get("target_language") or doc.get("language")


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
        own = [seg for seg, seg_label in raw if seg_label == label]
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


def _write_diarize_outputs(ctx: StageContext, doc: dict, speakers: SpeakersDoc) -> list[str]:
    """speakers.json plus segments.diarized.json: the segments the stage read
    with each one's speaker written back, so a transcript can carry speakers
    even when no translation ever happens."""
    speakers_path = ctx.artifacts.write_json(
        ctx.stage_index + 1, "speakers.json", speakers.model_dump()
    )
    speaker_of = {a.id: a.speaker for a in speakers.segments}
    diarized_path = ctx.artifacts.write_json(
        ctx.stage_index + 1,
        "segments.diarized.json",
        {
            "language": doc.get("language"),
            "target_language": doc.get("target_language"),
            "segments": [
                {**seg, "speaker": speaker_of.get(seg["id"], "")}
                for seg in doc["segments"]
            ],
        },
    )
    return [speakers_path.name, diarized_path.name]


@registry.register
class DiarizeStage:
    type = "diarize"

    def run(self, ctx: StageContext) -> StageResult:
        data = _read_dub_text(ctx)
        if _voice_mode(ctx.params) != "clone":
            # No per-speaker cloning ahead, so diarization (and its speaker
            # review pause) has nothing to contribute: one speaker covers all.
            doc = build_speakers_doc(data["segments"], [])
            names = _write_diarize_outputs(ctx, data, doc)
            ctx.emit_progress(1, 1)
            return StageResult(artifacts=names, skip_pause=True)
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
            turns = client.diarize(
                audio_path, num_speakers=ctx.params.get("num_speakers")
            )
        except DubbingError as error:
            raise StageError(str(error)) from error
        finally:
            client.close()

        doc = build_speakers_doc(data["segments"], turns)
        names = _write_diarize_outputs(ctx, data, doc)
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=names)


MAX_REF_SECONDS = 12.0
MIN_REF_SECONDS = 0.5


def _read_dub_inputs(ctx: StageContext, *names: str) -> list[dict]:
    docs = []
    for name in names:
        try:
            docs.append(ctx.artifacts.read_latest_json(name))
        except FileNotFoundError as error:
            raise StageError(f"stage requires a {name} artifact") from error
    return docs


@registry.register
class TtsSynthesizeStage:
    type = "tts_synthesize"

    def run(self, ctx: StageContext) -> StageResult:
        text_doc = _read_dub_text(ctx)
        dub_text = _dub_text_mode(ctx.params)
        (speakers_doc,) = _read_dub_inputs(ctx, "speakers.json")
        mode = _voice_mode(ctx.params)
        if mode == "preview":
            if not preview.say_available():
                raise StageError(
                    "system voice preview needs macOS with the say command"
                )
        else:
            _require_engine(ctx.data_root)
        if not ffmpeg_available():
            raise StageError("ffmpeg/ffprobe not found on PATH")
        config = load_config(ctx.data_root)
        segments = text_doc["segments"]
        speakers = {s["id"]: s for s in speakers_doc["speakers"]}
        speaker_of = {a["id"]: a["speaker"] for a in speakers_doc["segments"]}
        default_speaker = next(iter(speakers), "")

        out_index = ctx.stage_index + 1
        dub_dir = ctx.artifacts.path_for(out_index, "dub")
        dub_dir.mkdir(parents=True, exist_ok=True)

        refs: dict[str, Path] = {}
        ref_names: list[str] = []
        # User-supplied per-speaker reference audio wins over the clip
        # extracted from the original input. Only cloning needs references;
        # design shapes the voice from the instruction, preview uses say.
        reference_wavs = ctx.params.get("reference_wavs") or {}
        if mode == "clone":
            for speaker_id, speaker in speakers.items():
                custom = reference_wavs.get(speaker_id)
                if custom:
                    custom_path = Path(custom)
                    if not custom_path.exists():
                        raise StageError(
                            f"reference audio for {speaker_id} not found: {custom}"
                        )
                    refs[speaker_id] = custom_path
                    continue
                ref_path = ctx.artifacts.path_for(out_index, f"ref-{speaker_id}.wav")
                duration = min(
                    max(speaker["ref_end"] - speaker["ref_start"], MIN_REF_SECONDS),
                    MAX_REF_SECONDS,
                )
                try:
                    run_media(
                        build_extract_clip_cmd(
                            Path(ctx.task.input_path),
                            speaker["ref_start"],
                            duration,
                            ref_path,
                        )
                    )
                except MediaError as error:
                    raise StageError(str(error)) from error
                refs[speaker_id] = ref_path
                ref_names.append(ref_path.name)

        say_voice: str | None = None
        say_rate = int(ctx.params.get("preview_rate", preview.PREVIEW_BASE_RATE))
        if mode == "preview":
            say_voice = ctx.params.get("preview_voice") or preview.pick_voice(
                preview.list_voices(), _dub_voice_language(text_doc, dub_text)
            )

        manifest_path = ctx.artifacts.path_for(out_index, "dub-manifest.json")
        done: dict[int, dict] = {}
        if manifest_path.exists():
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in previous.get("segments", []):
                if (
                    entry.get("status") == "synthesized"
                    and entry.get("file")
                    and (ctx.artifacts.dir / entry["file"]).exists()
                ):
                    done[entry["id"]] = entry

        client = None if mode == "preview" else _make_client(ctx.data_root, config)
        entries: list[DubSegment] = []
        last_error = ""
        try:
            for n, seg in enumerate(segments):
                previous = done.get(seg["id"])
                if previous is not None:
                    entries.append(DubSegment.model_validate(previous))
                    ctx.emit_progress(n + 1, len(segments))
                    continue
                speaker_id = speaker_of.get(seg["id"], default_speaker)
                speaker = speakers.get(speaker_id)
                ext = "aiff" if mode == "preview" else "wav"
                out_path = dub_dir / f"seg-{seg['id']}.{ext}"
                text = _dub_segment_text(seg, dub_text)
                if not text:
                    entry = DubSegment(
                        id=seg["id"], speaker=speaker_id, status="failed",
                        error="empty dub text",
                    )
                else:
                    try:
                        if mode == "preview":
                            duration = preview.synthesize_preview(
                                text, out_path, voice=say_voice, rate=say_rate
                            )
                        else:
                            prompt_wav = refs.get(speaker_id)
                            response = client.synthesize(
                                text,
                                out=out_path,
                                prompt_wav=prompt_wav,
                                prompt_text=(speaker or {}).get("ref_text") or None
                                if prompt_wav is not None
                                else None,
                                instruction=ctx.params.get("voice_instruction") or None,
                                **_synth_options(config, ctx.params),
                            )
                            duration = response["duration"]
                        entry = DubSegment(
                            id=seg["id"],
                            speaker=speaker_id,
                            file=f"{out_index:02d}-dub/seg-{seg['id']}.{ext}",
                            duration=duration,
                        )
                    except DubbingError as error:
                        last_error = str(error)
                        entry = DubSegment(
                            id=seg["id"], speaker=speaker_id, status="failed",
                            error=last_error,
                        )
                entries.append(entry)
                ctx.artifacts.write_json(
                    out_index,
                    "dub-manifest.json",
                    DubManifestDoc(segments=entries).model_dump(),
                )
                ctx.emit_progress(n + 1, len(segments))
        finally:
            if client is not None:
                client.close()

        if not any(e.status == "synthesized" for e in entries):
            raise StageError(
                "no segments could be synthesized"
                + (f": {last_error}" if last_error else "")
            )
        return StageResult(artifacts=[manifest_path.name, *ref_names])


@registry.register
class AlignDurationStage:
    type = "align_duration"

    def run(self, ctx: StageContext) -> StageResult:
        text_doc = _read_dub_text(ctx)
        dub_text = _dub_text_mode(ctx.params)
        speakers_doc, manifest = _read_dub_inputs(
            ctx, "speakers.json", "dub-manifest.json"
        )
        mode = _voice_mode(ctx.params)
        if mode == "preview":
            if not preview.say_available():
                raise StageError(
                    "system voice preview needs macOS with the say command"
                )
        else:
            _require_engine(ctx.data_root)
        if not ffmpeg_available():
            raise StageError("ffmpeg/ffprobe not found on PATH")
        config = load_config(ctx.data_root)
        tolerance = ctx.params.get("tolerance", 1.1)
        max_tempo = ctx.params.get("max_tempo", 1.4)

        say_voice: str | None = None
        say_rate = int(ctx.params.get("preview_rate", preview.PREVIEW_BASE_RATE))
        if mode == "preview":
            say_voice = ctx.params.get("preview_voice") or preview.pick_voice(
                preview.list_voices(), _dub_voice_language(text_doc, dub_text)
            )

        seg_by_id = {s["id"]: s for s in text_doc["segments"]}
        speakers = {s["id"]: s for s in speakers_doc["speakers"]}
        out_index = ctx.stage_index + 1
        out_dir = ctx.artifacts.path_for(out_index, "dub")
        out_dir.mkdir(parents=True, exist_ok=True)

        client = None if mode == "preview" else _make_client(ctx.data_root, config)
        timeline: list[TimelineSegment] = []
        total = len(manifest["segments"])
        try:
            for n, entry in enumerate(manifest["segments"]):
                seg = seg_by_id.get(entry["id"])
                start = seg["start"] if seg else 0.0
                window = (seg["end"] - seg["start"]) if seg else 0.0
                if entry.get("status") != "synthesized" or seg is None:
                    timeline.append(
                        TimelineSegment(
                            id=entry["id"], start=start, window=window,
                            duration=0.0, status="failed",
                        )
                    )
                    ctx.emit_progress(n + 1, total)
                    continue

                duration = entry["duration"]
                file = entry["file"]
                regenerated = False
                plan = plan_segment(
                    window, duration, tolerance=tolerance, max_tempo=max_tempo,
                    can_regen=True,
                )
                if plan["action"] == "regen":
                    regen_ext = "aiff" if mode == "preview" else "wav"
                    regen_path = out_dir / f"seg-{entry['id']}.regen.{regen_ext}"
                    try:
                        if mode == "preview":
                            duration = preview.synthesize_preview(
                                _dub_segment_text(seg, dub_text),
                                regen_path,
                                voice=say_voice,
                                rate=preview.fit_rate(window, duration, base=say_rate),
                            )
                        else:
                            speaker = speakers.get(entry.get("speaker", ""))
                            prompt_wav: Path | None = None
                            if mode == "clone":
                                try:
                                    prompt_wav = ctx.artifacts.latest_path(
                                        f"ref-{entry.get('speaker', '')}.wav"
                                    )
                                except FileNotFoundError:
                                    prompt_wav = None
                            faster = "speak faster"
                            voice_instruction = ctx.params.get("voice_instruction")
                            if voice_instruction:
                                faster = f"speak faster; {voice_instruction}"
                            response = client.synthesize(
                                _dub_segment_text(seg, dub_text),
                                out=regen_path,
                                prompt_wav=prompt_wav,
                                prompt_text=(speaker or {}).get("ref_text") or None
                                if prompt_wav is not None
                                else None,
                                instruction=faster,
                                **_synth_options(config, ctx.params),
                            )
                            duration = response["duration"]
                        file = f"{out_index:02d}-dub/seg-{entry['id']}.regen.{regen_ext}"
                        regenerated = True
                    except DubbingError:
                        pass  # keep the original clip; atempo may still fit it
                    plan = plan_segment(
                        window, duration, tolerance=tolerance,
                        max_tempo=max_tempo, can_regen=False,
                    )

                tempo = 1.0
                status = "fit"
                if plan["action"] in ("atempo", "overflow"):
                    tempo = plan["tempo"]
                    status = plan["action"]
                    tempo_path = out_dir / f"seg-{entry['id']}.tempo.wav"
                    try:
                        run_media(
                            build_atempo_cmd(
                                ctx.artifacts.dir / file, tempo, tempo_path
                            )
                        )
                    except MediaError as error:
                        raise StageError(str(error)) from error
                    file = f"{out_index:02d}-dub/seg-{entry['id']}.tempo.wav"
                    duration = duration / tempo

                timeline.append(
                    TimelineSegment(
                        id=entry["id"], start=start, window=window,
                        duration=duration, tempo=tempo,
                        regenerated=regenerated, file=file, status=status,
                    )
                )
                ctx.emit_progress(n + 1, total)
        finally:
            if client is not None:
                client.close()

        path = ctx.artifacts.write_json(
            out_index,
            "dub-timeline.json",
            DubTimelineDoc(segments=timeline).model_dump(),
        )
        return StageResult(artifacts=[path.name])


@registry.register
class MixAudioStage:
    type = "mix_audio"

    def run(self, ctx: StageContext) -> StageResult:
        (timeline,) = _read_dub_inputs(ctx, "dub-timeline.json")
        if not ffmpeg_available():
            raise StageError("ffmpeg/ffprobe not found on PATH")
        placed = [
            s
            for s in timeline["segments"]
            if s.get("status") != "failed" and s.get("file")
        ]
        if not placed:
            raise StageError("no synthesized segments to mix")

        out_index = ctx.stage_index + 1
        orig_path = ctx.artifacts.path_for(out_index, "orig-audio.wav")
        orig_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            run_media(
                build_extract_mix_audio_cmd(Path(ctx.task.input_path), orig_path)
            )
        except MediaError as error:
            raise StageError(str(error)) from error

        clips = [ctx.artifacts.dir / s["file"] for s in placed]
        offsets = [s["start"] for s in placed]
        duck_windows = [(s["start"], s["start"] + s["duration"]) for s in placed]
        script_path = ctx.artifacts.path_for(out_index, "mix.filter")
        script_path.write_text(
            build_mix_filter_script(
                offsets, duck_windows, ctx.params.get("duck_volume", 0.2)
            ),
            encoding="utf-8",
        )
        mix_path = ctx.artifacts.path_for(out_index, "dub-mix.wav")
        try:
            run_media(build_mix_cmd(orig_path, clips, script_path, mix_path))
        except MediaError as error:
            raise StageError(str(error)) from error
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[mix_path.name, script_path.name])


@registry.register
class MuxStage:
    type = "mux"

    def run(self, ctx: StageContext) -> StageResult:
        if not ffmpeg_available():
            raise StageError("ffmpeg/ffprobe not found on PATH")
        try:
            mix_path = ctx.artifacts.latest_path("dub-mix.wav")
        except FileNotFoundError as error:
            raise StageError("mux stage requires a dub-mix artifact") from error
        output = ctx.artifacts.path_for(
            ctx.stage_index + 1, ctx.params.get("output_name", "video-dubbed.mp4")
        )
        try:
            run_media(build_mux_cmd(Path(ctx.task.input_path), mix_path, output))
        except MediaError as error:
            raise StageError(str(error)) from error
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[output.name])
