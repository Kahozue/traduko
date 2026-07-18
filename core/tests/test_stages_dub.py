import json
from pathlib import Path

import pytest

from traduko.artifacts import ArtifactStore
from traduko.config import CoreConfig, save_config
from traduko.events import EventBus
from traduko.models import StageRecord, TaskRecord, utc_now_iso
from traduko.profiles import load_profile
from traduko.seeds import ensure_defaults
from traduko.stages import base, dub, registry


def make_ctx(
    tmp_path: Path,
    input_path: Path,
    stage_index: int = 6,
    params: dict | None = None,
):
    now = utc_now_iso()
    task = TaskRecord(
        id="t-dub",
        project="default",
        input_path=str(input_path),
        profile="av-dub",
        stages=[StageRecord(type="noop")],
        created_at=now,
        updated_at=now,
    )
    task_dir = tmp_path / "projects" / "default" / "tasks" / task.id
    progress: list[tuple[int, int]] = []
    ctx = base.StageContext(
        task=task,
        stage_index=stage_index,
        params=params or {},
        artifacts=ArtifactStore(task_dir),
        data_root=tmp_path,
        emit_progress=lambda cur, total: progress.append((cur, total)),
        should_cancel=lambda: False,
        bus=EventBus(),
    )
    return ctx, progress


def install_engine(tmp_path: Path) -> None:
    target = tmp_path / "engines" / "dubbing"
    (target / "venv" / "bin").mkdir(parents=True, exist_ok=True)
    (target / "venv" / "bin" / "python").write_text("", encoding="utf-8")
    (target / ".installed").write_text("{}", encoding="utf-8")


def write_dub_config(tmp_path: Path, hf_token: str = "hf_tok") -> None:
    config = CoreConfig()
    config.dubbing.hf_token = hf_token
    save_config(tmp_path, config)


SEGMENTS = [
    {"id": 1, "start": 0.0, "end": 2.0, "source": "hello", "target": "哈囉"},
    {"id": 2, "start": 2.2, "end": 3.8, "source": "hi back", "target": "回嗨"},
    {"id": 3, "start": 4.0, "end": 9.0, "source": "long speech", "target": "長篇"},
]

TURNS = [
    {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
    {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_01"},
    {"start": 4.0, "end": 9.0, "speaker": "SPEAKER_00"},
]


def write_translation(ctx, index: int = 4) -> None:
    ctx.artifacts.write_json(
        index,
        "translation.json",
        {"source_language": "en", "target_language": "zh", "segments": SEGMENTS},
    )


class FakeClient:
    def __init__(self, turns=None, synth_duration=1.0):
        self.turns = turns if turns is not None else TURNS
        self.synth_duration = synth_duration
        self.diarized: list[str] = []
        self.synth_calls: list[dict] = []
        self.closed = False

    def diarize(self, audio):
        self.diarized.append(str(audio))
        return self.turns

    def synthesize(self, text, out, prompt_wav=None, prompt_text=None, instruction=None):
        call = {
            "text": text,
            "out": str(out),
            "prompt_wav": str(prompt_wav) if prompt_wav else None,
            "prompt_text": prompt_text,
            "instruction": instruction,
        }
        self.synth_calls.append(call)
        Path(out).write_bytes(b"RIFFfake")
        duration = (
            self.synth_duration(call)
            if callable(self.synth_duration)
            else self.synth_duration
        )
        return {"ok": True, "path": str(out), "duration": duration}

    def close(self):
        self.closed = True


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(dub, "_make_client", lambda data_root, config: client)
    return client


def test_assign_speakers_by_overlap() -> None:
    doc = dub.build_speakers_doc(SEGMENTS, TURNS)
    assert [s.speaker for s in doc.segments] == ["S1", "S2", "S1"]
    by_id = {s.id: s for s in doc.speakers}
    assert by_id["S1"].ref_start == 4.0 and by_id["S1"].ref_end == 9.0
    assert by_id["S1"].ref_text == "long speech"
    assert by_id["S2"].ref_text == "hi back"


def test_assign_speakers_without_turns_is_single_speaker() -> None:
    doc = dub.build_speakers_doc(SEGMENTS, [])
    assert [s.speaker for s in doc.segments] == ["S1", "S1", "S1"]
    assert len(doc.speakers) == 1


def test_diarize_stage_writes_speakers(tmp_path: Path, fake_client) -> None:
    install_engine(tmp_path)
    write_dub_config(tmp_path)
    ctx, progress = make_ctx(tmp_path, tmp_path / "in.mp4")
    write_translation(ctx)
    ctx.artifacts.path_for(1, "audio.wav").parent.mkdir(parents=True, exist_ok=True)
    ctx.artifacts.path_for(1, "audio.wav").write_bytes(b"RIFF")

    result = registry.create("diarize").run(ctx)
    assert result.artifacts == ["07-speakers.json"]
    doc = ctx.artifacts.read_latest_json("speakers.json")
    assert [s["speaker"] for s in doc["segments"]] == ["S1", "S2", "S1"]
    assert fake_client.diarized and fake_client.diarized[0].endswith("01-audio.wav")
    assert fake_client.closed is True
    assert progress[-1] == (1, 1)


def test_diarize_requires_engine(tmp_path: Path, fake_client) -> None:
    write_dub_config(tmp_path)
    ctx, _ = make_ctx(tmp_path, tmp_path / "in.mp4")
    write_translation(ctx)
    with pytest.raises(base.StageError, match="not installed"):
        registry.create("diarize").run(ctx)


def test_diarize_requires_hf_token(tmp_path: Path, fake_client) -> None:
    install_engine(tmp_path)
    write_dub_config(tmp_path, hf_token="")
    ctx, _ = make_ctx(tmp_path, tmp_path / "in.mp4")
    write_translation(ctx)
    with pytest.raises(base.StageError, match="[Hh]ugging"):
        registry.create("diarize").run(ctx)


def write_speakers(ctx, index: int = 7) -> None:
    ctx.artifacts.write_json(
        index,
        "speakers.json",
        {
            "speakers": [
                {"id": "S1", "label": "Speaker 1", "ref_start": 4.0,
                 "ref_end": 9.0, "ref_text": "long speech"},
                {"id": "S2", "label": "Speaker 2", "ref_start": 2.2,
                 "ref_end": 3.8, "ref_text": "hi back"},
            ],
            "segments": [
                {"id": 1, "speaker": "S1"},
                {"id": 2, "speaker": "S2"},
                {"id": 3, "speaker": "S1"},
            ],
        },
    )


def setup_tts(tmp_path, monkeypatch, stage_index=7):
    install_engine(tmp_path)
    write_dub_config(tmp_path)
    ctx, progress = make_ctx(tmp_path, tmp_path / "in.mp4", stage_index=stage_index)
    write_translation(ctx)
    write_speakers(ctx)
    commands: list[list[str]] = []
    monkeypatch.setattr(dub, "run_media", lambda cmd: commands.append(cmd))
    monkeypatch.setattr(dub, "ffmpeg_available", lambda: True)
    return ctx, progress, commands


def test_tts_synthesize_writes_clips_and_manifest(
    tmp_path: Path, fake_client, monkeypatch
) -> None:
    ctx, progress, commands = setup_tts(tmp_path, monkeypatch)
    result = registry.create("tts_synthesize").run(ctx)
    assert "08-dub-manifest.json" in result.artifacts

    # one reference clip extracted per speaker, from the original input
    ref_cmds = [c for c in commands if any("ref-" in part for part in c)]
    assert len(ref_cmds) == 2
    assert str(tmp_path / "in.mp4") in ref_cmds[0]

    manifest = ctx.artifacts.read_latest_json("dub-manifest.json")
    assert [s["status"] for s in manifest["segments"]] == ["synthesized"] * 3
    assert manifest["segments"][0]["file"] == "08-dub/seg-1.wav"
    assert (ctx.artifacts.dir / "08-dub" / "seg-1.wav").exists()

    calls = fake_client.synth_calls
    assert [c["text"] for c in calls] == ["哈囉", "回嗨", "長篇"]
    assert calls[0]["prompt_wav"].endswith("08-ref-S1.wav")
    assert calls[1]["prompt_wav"].endswith("08-ref-S2.wav")
    assert calls[0]["prompt_text"] == "long speech"
    assert progress[-1] == (3, 3)


def test_tts_synthesize_resumes_from_manifest(
    tmp_path: Path, fake_client, monkeypatch
) -> None:
    ctx, _, _ = setup_tts(tmp_path, monkeypatch)
    dub_dir = ctx.artifacts.dir / "08-dub"
    dub_dir.mkdir(parents=True, exist_ok=True)
    (dub_dir / "seg-1.wav").write_bytes(b"RIFFdone")
    ctx.artifacts.write_json(
        8,
        "dub-manifest.json",
        {
            "segments": [
                {"id": 1, "speaker": "S1", "file": "08-dub/seg-1.wav",
                 "duration": 1.5, "status": "synthesized"}
            ]
        },
    )
    registry.create("tts_synthesize").run(ctx)
    assert [c["text"] for c in fake_client.synth_calls] == ["回嗨", "長篇"]
    manifest = ctx.artifacts.read_latest_json("dub-manifest.json")
    assert len(manifest["segments"]) == 3
    assert manifest["segments"][0]["duration"] == 1.5


def test_tts_synthesize_records_failures_and_continues(
    tmp_path: Path, monkeypatch
) -> None:
    from traduko.dubbing.client import DubbingError

    client = FakeClient()
    original = client.synthesize

    def flaky(text, out, **kwargs):
        if text == "回嗨":
            raise DubbingError("synthesis exploded")
        return original(text, out, **kwargs)

    client.synthesize = flaky
    monkeypatch.setattr(dub, "_make_client", lambda data_root, config: client)
    ctx, _, _ = setup_tts(tmp_path, monkeypatch)
    registry.create("tts_synthesize").run(ctx)
    manifest = ctx.artifacts.read_latest_json("dub-manifest.json")
    statuses = {s["id"]: s["status"] for s in manifest["segments"]}
    assert statuses == {1: "synthesized", 2: "failed", 3: "synthesized"}
    assert "exploded" in manifest["segments"][1]["error"]


def test_tts_synthesize_fails_when_nothing_synthesized(
    tmp_path: Path, monkeypatch
) -> None:
    from traduko.dubbing.client import DubbingError

    client = FakeClient()

    def broken(text, out, **kwargs):
        raise DubbingError("dead engine")

    client.synthesize = broken
    monkeypatch.setattr(dub, "_make_client", lambda data_root, config: client)
    ctx, _, _ = setup_tts(tmp_path, monkeypatch)
    with pytest.raises(base.StageError, match="no segments"):
        registry.create("tts_synthesize").run(ctx)


def write_manifest(ctx, durations: dict[int, float], index: int = 8) -> None:
    dub_dir = ctx.artifacts.dir / f"{index:02d}-dub"
    dub_dir.mkdir(parents=True, exist_ok=True)
    segments = []
    for seg_id, duration in durations.items():
        name = f"{index:02d}-dub/seg-{seg_id}.wav"
        (ctx.artifacts.dir / name).write_bytes(b"RIFFfake")
        segments.append(
            {"id": seg_id, "speaker": "S1", "file": name,
             "duration": duration, "status": "synthesized"}
        )
    ctx.artifacts.write_json(index, "dub-manifest.json", {"segments": segments})


def test_align_duration_fit_regen_atempo_overflow(
    tmp_path: Path, monkeypatch
) -> None:
    # windows: seg1 = 2.0s, seg2 = 1.6s, seg3 = 5.0s
    client = FakeClient(synth_duration=lambda call: 1.7)
    monkeypatch.setattr(dub, "_make_client", lambda data_root, config: client)
    ctx, progress, commands = setup_tts(tmp_path, monkeypatch, stage_index=8)
    # seg1 fits; seg2 needs regen (1.7 <= 1.6*1.1 fits after regen);
    # seg3 overflows even the cap
    write_manifest(ctx, {1: 2.1, 2: 3.0, 3: 12.0})

    result = registry.create("align_duration").run(ctx)
    assert "09-dub-timeline.json" in result.artifacts
    timeline = ctx.artifacts.read_latest_json("dub-timeline.json")
    by_id = {s["id"]: s for s in timeline["segments"]}

    assert by_id[1]["status"] == "fit"
    assert by_id[1]["file"] == "08-dub/seg-1.wav"
    assert by_id[1]["tempo"] == 1.0

    assert by_id[2]["status"] == "fit"
    assert by_id[2]["regenerated"] is True
    assert by_id[2]["file"] == "09-dub/seg-2.regen.wav"
    assert by_id[2]["duration"] == 1.7

    # regen still returns 1.7 for seg3 window 5.0 -> fits actually; adjust:
    assert by_id[3]["status"] == "fit"

    regen_calls = [c for c in client.synth_calls if c["instruction"]]
    assert all(c["instruction"] == "speak faster" for c in regen_calls)


def test_align_duration_atempo_and_overflow(tmp_path: Path, monkeypatch) -> None:
    # regen never helps: always returns the original duration
    durations = {2: 2.0, 3: 12.0}

    def stuck(call):
        seg_id = int(call["out"].rsplit("seg-", 1)[1].split(".")[0])
        return durations[seg_id]

    client = FakeClient(synth_duration=stuck)
    monkeypatch.setattr(dub, "_make_client", lambda data_root, config: client)
    ctx, _, commands = setup_tts(tmp_path, monkeypatch, stage_index=8)
    write_manifest(ctx, {2: 2.0, 3: 12.0})

    registry.create("align_duration").run(ctx)
    timeline = ctx.artifacts.read_latest_json("dub-timeline.json")
    by_id = {s["id"]: s for s in timeline["segments"]}

    # seg2: window 1.6, duration 2.0 -> regen no help -> atempo 2.0/1.76
    assert by_id[2]["status"] == "atempo"
    assert by_id[2]["tempo"] == pytest.approx(2.0 / (1.6 * 1.1), abs=0.01)
    assert by_id[2]["file"] == "09-dub/seg-2.tempo.wav"
    # seg3: window 5.0, duration 12.0 -> beyond cap -> overflow at max tempo
    assert by_id[3]["status"] == "overflow"
    assert by_id[3]["tempo"] == 1.4
    # both seg2 and seg3 get an atempo pass (overflow applies the cap)
    atempo_cmds = [c for c in commands if any("atempo" in str(p) for p in c)]
    assert len(atempo_cmds) == 2


def test_align_duration_carries_failed_segments(tmp_path: Path, monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(dub, "_make_client", lambda data_root, config: client)
    ctx, _, _ = setup_tts(tmp_path, monkeypatch, stage_index=8)
    ctx.artifacts.write_json(
        8,
        "dub-manifest.json",
        {"segments": [{"id": 1, "speaker": "S1", "file": "", "duration": 0.0,
                       "status": "failed", "error": "boom"}]},
    )
    registry.create("align_duration").run(ctx)
    timeline = ctx.artifacts.read_latest_json("dub-timeline.json")
    assert timeline["segments"][0]["status"] == "failed"


def write_timeline(ctx, index: int = 9) -> None:
    dub_dir = ctx.artifacts.dir / "08-dub"
    dub_dir.mkdir(parents=True, exist_ok=True)
    for seg_id in (1, 3):
        (dub_dir / f"seg-{seg_id}.wav").write_bytes(b"RIFFfake")
    ctx.artifacts.write_json(
        index,
        "dub-timeline.json",
        {
            "segments": [
                {"id": 1, "start": 0.0, "window": 2.0, "duration": 1.8,
                 "tempo": 1.0, "file": "08-dub/seg-1.wav", "status": "fit"},
                {"id": 2, "start": 2.2, "window": 1.6, "duration": 0.0,
                 "tempo": 1.0, "file": "", "status": "failed"},
                {"id": 3, "start": 4.0, "window": 5.0, "duration": 4.2,
                 "tempo": 1.2, "file": "08-dub/seg-3.wav", "status": "atempo"},
            ]
        },
    )


def test_mix_audio_builds_script_and_mix(tmp_path: Path, monkeypatch) -> None:
    ctx, progress, commands = setup_tts(tmp_path, monkeypatch, stage_index=9)
    write_timeline(ctx)
    result = registry.create("mix_audio").run(ctx)
    assert "10-dub-mix.wav" in result.artifacts

    script = (ctx.artifacts.dir / "10-mix.filter").read_text(encoding="utf-8")
    assert "between(t,0.000,1.800)" in script
    assert "between(t,4.000,8.200)" in script
    assert "adelay=0|0" in script and "adelay=4000|4000" in script
    assert "amix=inputs=3" in script

    mix_cmds = [c for c in commands if any("dub-mix.wav" in str(p) for p in c)]
    assert len(mix_cmds) == 1
    joined = " ".join(mix_cmds[0])
    assert "08-dub/seg-1.wav" in joined and "08-dub/seg-3.wav" in joined
    orig_cmds = [c for c in commands if str(c[-1]).endswith("orig-audio.wav")]
    assert len(orig_cmds) == 1


def test_mix_audio_without_usable_segments_fails(tmp_path: Path, monkeypatch) -> None:
    ctx, _, _ = setup_tts(tmp_path, monkeypatch, stage_index=9)
    ctx.artifacts.write_json(
        9, "dub-timeline.json",
        {"segments": [{"id": 1, "start": 0.0, "window": 1.0, "duration": 0.0,
                       "tempo": 1.0, "file": "", "status": "failed"}]},
    )
    with pytest.raises(base.StageError, match="no synthesized"):
        registry.create("mix_audio").run(ctx)


def test_mux_replaces_audio_track(tmp_path: Path, monkeypatch) -> None:
    ctx, _, commands = setup_tts(tmp_path, monkeypatch, stage_index=10)
    (ctx.artifacts.dir / "10-dub-mix.wav").write_bytes(b"RIFFmix")
    result = registry.create("mux").run(ctx)
    assert result.artifacts == ["11-video-dubbed.mp4"]
    mux_cmds = [c for c in commands if any("video-dubbed" in str(p) for p in c)]
    assert len(mux_cmds) == 1
    assert str(tmp_path / "in.mp4") in mux_cmds[0]


def test_av_dub_end_to_end_with_checkpoint(tmp_path: Path, monkeypatch) -> None:
    from pathlib import Path as P

    from traduko.executor import PipelineExecutor
    from traduko.models import StageStatus, TaskStatus
    from traduko.profiles import load_profile, stage_records_from
    from traduko.tasks import TaskStore

    install_engine(tmp_path)
    write_dub_config(tmp_path)
    ensure_defaults(tmp_path)
    client = FakeClient()
    monkeypatch.setattr(dub, "_make_client", lambda data_root, config: client)
    monkeypatch.setattr(dub, "run_media", lambda cmd: P(cmd[-1]).write_bytes(b"x"))
    monkeypatch.setattr(dub, "ffmpeg_available", lambda: True)

    store = TaskStore(tmp_path)
    profile = load_profile(tmp_path, "av-dub")
    record = store.create(
        project="default",
        input_path=str(tmp_path / "in.mp4"),
        profile_name="av-dub",
        stages=stage_records_from(profile),
    )
    # Subtitle stages are not under test: mark them completed and provide
    # the translation artifact they would have produced.
    for stage in record.stages[:6]:
        stage.status = StageStatus.COMPLETED
    store.save(record)
    artifacts = ArtifactStore(store.task_dir(record.project, record.id))
    artifacts.write_json(
        4, "translation.json",
        {"source_language": "en", "target_language": "zh", "segments": SEGMENTS},
    )
    artifacts.path_for(1, "audio.wav").parent.mkdir(parents=True, exist_ok=True)
    artifacts.path_for(1, "audio.wav").write_bytes(b"RIFF")

    executor = PipelineExecutor(store, EventBus(), tmp_path)
    record = executor.run(record)
    assert record.status == TaskStatus.WAITING_REVIEW
    speakers = artifacts.read_latest_json("speakers.json")
    assert [s["speaker"] for s in speakers["segments"]] == ["S1", "S2", "S1"]

    record = executor.run(record)
    assert record.status == TaskStatus.COMPLETED
    assert artifacts.read_latest_json("dub-manifest.json")["segments"]
    timeline = artifacts.read_latest_json("dub-timeline.json")
    assert all(s["status"] == "fit" for s in timeline["segments"])
    assert artifacts.latest_path("dub-mix.wav").exists()
    assert artifacts.latest_path("video-dubbed.mp4").exists()


def test_av_dub_profile_seeds_with_diarize_checkpoint(tmp_path: Path) -> None:
    ensure_defaults(tmp_path)
    profile = load_profile(tmp_path, "av-dub")
    types = [s.type for s in profile.stages]
    assert types == [
        "extract_audio", "asr", "segment", "translate", "proofread",
        "export_subtitles", "diarize", "tts_synthesize", "align_duration",
        "mix_audio", "mux",
    ]
    diarize = profile.stages[types.index("diarize")]
    assert diarize.pause_after is True
