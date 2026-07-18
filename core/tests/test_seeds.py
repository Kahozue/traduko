from pathlib import Path

from traduko.profiles import load_profile
from traduko.seeds import ensure_defaults
from traduko.workspace import Workspace

SEED_FILES = [
    "profiles/av-default.yaml",
    "profiles/subtitle-translate.yaml",
    "profiles/novel-translate.yaml",
    "prompts/translate.txt",
    "prompts/proofread.txt",
    "prompts/doc-translate.txt",
    "prompts/doc-summary.txt",
    "config/pricing.yaml",
    "config/styles.yaml",
]


def test_ensure_defaults_creates_seed_files(tmp_path: Path) -> None:
    ensure_defaults(tmp_path)
    for rel in SEED_FILES:
        assert (tmp_path / rel).is_file(), rel


def test_seeded_profiles_are_loadable(tmp_path: Path) -> None:
    ensure_defaults(tmp_path)
    av = load_profile(tmp_path, "av-default")
    assert [s.type for s in av.stages] == [
        "extract_audio", "asr", "segment", "translate", "proofread",
        "export_subtitles",
    ]
    sub = load_profile(tmp_path, "subtitle-translate")
    assert [s.type for s in sub.stages] == [
        "ingest_subtitle", "translate", "proofread", "export_subtitles",
    ]
    assert sub.stages[1].params["provider"] == "fake"
    novel = load_profile(tmp_path, "novel-translate")
    assert [s.type for s in novel.stages] == [
        "ingest_document", "chunk", "translate_chunks", "qc_scan",
        "translate_chunks", "qc_scan", "export_document",
    ]
    assert novel.stages[1].params["base_chars"] == 2600
    assert novel.stages[2].params["provider"] == "fake"
    assert novel.stages[4].params["only_flagged"] is True


def test_ensure_defaults_never_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "prompts" / "translate.txt"
    target.parent.mkdir(parents=True)
    target.write_text("my custom template ${segments_json}", encoding="utf-8")
    ensure_defaults(tmp_path)
    assert target.read_text(encoding="utf-8") == "my custom template ${segments_json}"


def test_workspace_open_seeds_defaults(tmp_path: Path) -> None:
    Workspace.open(tmp_path)
    for rel in SEED_FILES:
        assert (tmp_path / rel).is_file(), rel


def test_audio_profiles_seeded_with_audio_kind(tmp_path):
    from traduko.profiles import load_profile, profile_kind
    from traduko.seeds import ensure_defaults

    ensure_defaults(tmp_path)
    for name in ("audio-transcribe", "audio-translate", "audio-dub"):
        profile = load_profile(tmp_path, name)
        assert profile_kind(profile) == "audio", name
    transcribe = load_profile(tmp_path, "audio-transcribe")
    types = [stage.type for stage in transcribe.stages]
    assert types == ["extract_audio", "asr", "export_transcript"]
    asr_stage = transcribe.stages[1]
    assert asr_stage.params.get("engine") == "auto_audio"
    dub = load_profile(tmp_path, "audio-dub")
    assert dub.stages[-1].type == "export_audio"
    assert any(stage.pause_after for stage in dub.stages)
