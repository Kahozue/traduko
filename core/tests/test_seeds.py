from pathlib import Path

from traduko.profiles import load_profile
from traduko.seeds import ensure_defaults
from traduko.workspace import Workspace

SEED_FILES = [
    "profiles/av-default.yaml",
    "profiles/subtitle-translate.yaml",
    "prompts/translate.txt",
    "prompts/proofread.txt",
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
