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
from ..dubbing.engines import resolve_tts_engine
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
    media_kind_of,
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


def _seg_span(seg: dict) -> tuple[float, float] | None:
    """(start, end), or None for a transcript line that carries no timing."""
    start, end = seg.get("start"), seg.get("end")
    if start is None or end is None:
        return None
    return start, end


def _seg_duration(seg: dict) -> float:
    span = _seg_span(seg)
    return span[1] - span[0] if span else 0.0


def build_speakers_doc(segments: list[dict], turns: list[dict]) -> SpeakersDoc:
    """Assign each subtitle segment the diarization speaker with the most
    overlap (nearest turn when none overlaps; single speaker when
    diarization found nothing), then pick each speaker's longest segment
    as the voice-clone reference.

    An untimed segment has nothing to overlap against, so it falls to the
    first turn's speaker; its speaker's reference window then comes from a
    timed segment if that speaker has one."""
    raw: list[tuple[dict, str]] = []
    for seg in segments:
        span = _seg_span(seg)
        best, best_overlap = None, 0.0
        if span is None:
            best = turns[0]["speaker"] if turns else None
        else:
            for turn in turns:
                overlap = _overlap(span[0], span[1], turn["start"], turn["end"])
                if overlap > best_overlap:
                    best, best_overlap = turn["speaker"], overlap
            if best is None and turns:
                mid = (span[0] + span[1]) / 2
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
        ref = max(own, key=_seg_duration)
        ref_span = _seg_span(ref) or (0.0, 0.0)
        speakers.append(
            Speaker(
                id=speaker_id,
                label=f"Speaker {speaker_id[1:]}",
                ref_start=ref_span[0],
                ref_end=ref_span[1],
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
        # Guard: the studio writes tts_engine into params; a placeholder id
        # must be rejected here even if the UI's disabled state is bypassed.
        engine_id = ctx.params.get("tts_engine")
        if engine_id:
            try:
                resolve_tts_engine(engine_id)
            except DubbingError as error:
                raise StageError(str(error)) from error
        text_doc = _read_dub_text(ctx)
        dub_text = _dub_text_mode(ctx.params)
        # Speaker separation is optional (spec 4-(3)): a task whose diarize
        # stage is switched off or absent has no speakers.json, and one voice
        # covers every line. The fallback is written out below so
        # align_duration and mix_audio read it like any other.
        try:
            (speakers_doc,) = _read_dub_inputs(ctx, "speakers.json")
            fallback: SpeakersDoc | None = None
        except StageError:
            fallback = build_speakers_doc(text_doc["segments"], [])
            speakers_doc = fallback.model_dump()
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

        extra_names: list[str] = []
        if fallback is not None:
            extra_names.append(
                ctx.artifacts.write_json(out_index, "speakers.json", speakers_doc).name
            )

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
        return StageResult(artifacts=[manifest_path.name, *ref_names, *extra_names])


def _timeline_mode(segments: list[dict]) -> tuple[str, str]:
    """("timed"|"sequential", note). A transcript ingested from a plain text
    file carries no timing, so there is no window to fit a clip into and the
    clips have to be laid end to end. Partly timed input goes the same way,
    with a note on the artifact saying so: half a timeline is not a timeline.
    """
    timed = [
        s.get("start") is not None and s.get("end") is not None for s in segments
    ]
    if all(timed):
        return "timed", ""
    if any(timed):
        return (
            "sequential",
            "some transcript lines carry no timing, so every clip was laid "
            "end to end instead of being fitted to the original timing",
        )
    return "sequential", ""


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

        timeline_mode, timeline_note = _timeline_mode(text_doc["segments"])
        sequential = timeline_mode == "sequential"

        client = (
            None
            if mode == "preview" or sequential
            else _make_client(ctx.data_root, config)
        )
        timeline: list[TimelineSegment] = []
        cursor = 0.0
        total = len(manifest["segments"])
        try:
            for n, entry in enumerate(manifest["segments"]):
                seg = seg_by_id.get(entry["id"])
                if sequential:
                    # No window to fit into: each clip keeps its natural
                    # length and starts where the previous one ended.
                    synthesized = entry.get("status") == "synthesized" and seg
                    duration = entry["duration"] if synthesized else 0.0
                    timeline.append(
                        TimelineSegment(
                            id=entry["id"], start=cursor, window=duration,
                            duration=duration,
                            file=entry["file"] if synthesized else "",
                            status="fit" if synthesized else "failed",
                        )
                    )
                    cursor += duration
                    ctx.emit_progress(n + 1, total)
                    continue
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
            DubTimelineDoc(
                mode=timeline_mode, note=timeline_note, segments=timeline
            ).model_dump(),
        )
        return StageResult(artifacts=[path.name])


def _mix_base_source(ctx: StageContext) -> Path | None:
    """Where the mix bed comes from, or None for silence. params.base_audio
    wins (a compose video task can bring its own soundtrack), then the task
    input when it is actually a media file: a compose task's input is the
    transcript, which has no audio track to extract."""
    override = ctx.params.get("base_audio")
    if override:
        path = Path(override)
        if not path.exists():
            raise StageError(f"base audio not found: {path}")
        return path
    input_path = Path(ctx.task.input_path)
    return input_path if media_kind_of(input_path) else None


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
        source = _mix_base_source(ctx)
        orig_path: Path | None = None
        if source is not None:
            orig_path = ctx.artifacts.path_for(out_index, "orig-audio.wav")
            orig_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                run_media(build_extract_mix_audio_cmd(source, orig_path))
            except MediaError as error:
                raise StageError(str(error)) from error

        clips = [ctx.artifacts.dir / s["file"] for s in placed]
        offsets = [s["start"] for s in placed]
        # Ducking only makes sense against an original track; over silence
        # there is nothing to pull down.
        duck_windows = (
            [(s["start"], s["start"] + s["duration"]) for s in placed]
            if orig_path is not None
            else []
        )
        script_path = ctx.artifacts.path_for(out_index, "mix.filter")
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(
            build_mix_filter_script(
                offsets, duck_windows, ctx.params.get("duck_volume", 0.2)
            ),
            encoding="utf-8",
        )
        mix_path = ctx.artifacts.path_for(out_index, "dub-mix.wav")
        try:
            run_media(
                build_mix_cmd(
                    orig_path,
                    clips,
                    script_path,
                    mix_path,
                    silence_duration=max(
                        (s["start"] + s["duration"] for s in placed), default=0.0
                    ),
                )
            )
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
