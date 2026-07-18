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
        self.synth_calls.append(
            {
                "text": text,
                "out": str(out),
                "prompt_wav": str(prompt_wav) if prompt_wav else None,
                "prompt_text": prompt_text,
                "instruction": instruction,
            }
        )
        Path(out).write_bytes(b"RIFFfake")
        return {"ok": True, "path": str(out), "duration": self.synth_duration}

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
