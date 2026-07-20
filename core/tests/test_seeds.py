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
    "prompts/glossary_proofread.txt",
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


# The v2-01 novel-translate profile: the parse/repack shell, before
# translate_chunks slotted in. A data root seeded then kept producing
# document tasks that never translated anything.
_V2_01_NOVEL_TRANSLATE = """\
# Novel/document pipeline: markdown, txt, epub, or html in, same format
# out. v2-01 ships the parse/repack shell; the translate_chunks stage
# (v2-02) will slot in between chunk and export_document.
schema_version: 1
name: novel-translate
stages:
  - type: ingest_document
  - type: chunk
    params:
      base_blocks: 4
      base_chars: 2600
      max_blocks: 80
      max_chars: 5200
  - type: export_document
"""


def test_ensure_defaults_upgrades_an_untouched_older_profile(tmp_path: Path) -> None:
    target = tmp_path / "profiles" / "novel-translate.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(_V2_01_NOVEL_TRANSLATE, encoding="utf-8")

    ensure_defaults(tmp_path)

    upgraded = load_profile(tmp_path, "novel-translate")
    assert [s.type for s in upgraded.stages] == [
        "ingest_document", "chunk", "translate_chunks", "qc_scan",
        "translate_chunks", "qc_scan", "export_document",
    ]


def test_ensure_defaults_leaves_an_edited_profile_alone(tmp_path: Path) -> None:
    # One character off a shipped version is a user edit as far as we know.
    target = tmp_path / "profiles" / "novel-translate.yaml"
    target.parent.mkdir(parents=True)
    edited = _V2_01_NOVEL_TRANSLATE.replace("base_chars: 2600", "base_chars: 1200")
    target.write_text(edited, encoding="utf-8")

    ensure_defaults(tmp_path)

    assert target.read_text(encoding="utf-8") == edited


def test_ensure_defaults_is_idempotent_after_an_upgrade(tmp_path: Path) -> None:
    ensure_defaults(tmp_path)
    before = (tmp_path / "profiles" / "novel-translate.yaml").read_text(
        encoding="utf-8"
    )
    ensure_defaults(tmp_path)
    assert (tmp_path / "profiles" / "novel-translate.yaml").read_text(
        encoding="utf-8"
    ) == before


def test_every_shipped_seed_version_is_recorded() -> None:
    """_SHIPPED_VERSIONS is what lets an old data root receive a fixed
    pipeline, and it is only as good as its coverage. Rather than trusting
    whoever edits a seed to remember, read the versions out of the history
    and say which hash is missing."""
    import ast
    import subprocess

    from traduko.seeds import _SHIPPED_VERSIONS, content_hash

    rel_of = {
        "_PROFILE_AV_DEFAULT": "profiles/av-default.yaml",
        "_PROFILE_SUBTITLE_TRANSLATE": "profiles/subtitle-translate.yaml",
        "_PROFILE_NOVEL_TRANSLATE": "profiles/novel-translate.yaml",
        "_PROFILE_AV_DUB": "profiles/av-dub.yaml",
        "_PROFILE_TRANSLATE_PDF": "profiles/translate-pdf.yaml",
        "_PROFILE_AUDIO_TRANSCRIBE": "profiles/audio-transcribe.yaml",
        "_PROFILE_AUDIO_TRANSLATE": "profiles/audio-translate.yaml",
        "_PROFILE_AUDIO_DUB": "profiles/audio-dub.yaml",
        "_PROFILE_VIDEO_COMPOSE": "profiles/video-compose.yaml",
        "_PROFILE_AUDIO_COMPOSE": "profiles/audio-compose.yaml",
        "_STYLES_DEFAULT": "config/styles.yaml",
    }
    source_path = "core/src/traduko/seeds.py"
    repo = Path(__file__).resolve().parents[2]
    try:
        revisions = subprocess.run(
            ["git", "log", "--format=%H", "--", source_path],
            cwd=repo, capture_output=True, text=True, check=True, timeout=30,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        import pytest

        pytest.skip("not a git checkout")

    missing: list[str] = []
    for revision in revisions:
        blob = subprocess.run(
            ["git", "show", f"{revision}:{source_path}"],
            cwd=repo, capture_output=True, text=True, timeout=30,
        ).stdout
        if not blob:
            continue
        for node in ast.parse(blob).body:
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, ast.Constant):
                continue
            if not isinstance(node.value.value, str):
                continue
            for target in node.targets:
                rel = rel_of.get(getattr(target, "id", ""))
                if rel is None:
                    continue
                digest = content_hash(node.value.value)
                if digest not in _SHIPPED_VERSIONS.get(rel, frozenset()):
                    missing.append(f"{rel}: {digest} (shipped in {revision[:8]})")

    assert not missing, (
        "seeded files shipped in earlier commits are not recorded in "
        "_SHIPPED_VERSIONS, so those data roots will never be upgraded:\n"
        + "\n".join(sorted(set(missing)))
    )


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


def test_compose_profiles_seeded(tmp_path: Path) -> None:
    from traduko.profiles import profile_kind

    ensure_defaults(tmp_path)

    video = load_profile(tmp_path, "video-compose")
    assert profile_kind(video) == "video"
    assert [s.type for s in video.stages] == [
        "ingest_transcript", "diarize", "tts_synthesize", "align_duration",
        "mix_audio", "mux",
    ]

    audio = load_profile(tmp_path, "audio-compose")
    assert profile_kind(audio) == "audio"
    assert [s.type for s in audio.stages] == [
        "ingest_transcript", "diarize", "tts_synthesize", "align_duration",
        "mix_audio", "export_audio",
    ]


def test_compose_profiles_speak_the_transcript_as_is(tmp_path: Path) -> None:
    # The transcript is the dub text: there is no translation stage to wait
    # for, so the dub stages must not go looking for one.
    ensure_defaults(tmp_path)
    for name in ("video-compose", "audio-compose"):
        profile = load_profile(tmp_path, name)
        dub_stages = [
            s for s in profile.stages
            if s.type in ("diarize", "tts_synthesize", "align_duration")
        ]
        assert dub_stages
        for stage in dub_stages:
            assert stage.params.get("dub_text") == "original", (name, stage.type)


def test_audio_compose_defaults_to_designed_voices(tmp_path: Path) -> None:
    # Nothing to clone from: the input is a transcript, not a recording.
    ensure_defaults(tmp_path)
    profile = load_profile(tmp_path, "audio-compose")
    for stage in profile.stages:
        if stage.type in ("diarize", "tts_synthesize", "align_duration"):
            assert stage.params.get("voice_mode") == "design", stage.type
    video = load_profile(tmp_path, "video-compose")
    assert "voice_mode" not in video.stages[1].params


def test_profile_kind_classifies_a_comic_profile(tmp_path: Path) -> None:
    # No comic pipeline ships yet; the kind enum reserves the domain so a
    # comic profile is classified rather than falling back to video.
    from traduko.profiles import profile_kind

    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "profiles" / "comic-x.yaml").write_text(
        "schema_version: 1\nname: comic-x\nkind: comic\nstages:\n  - type: noop\n",
        encoding="utf-8",
    )
    assert profile_kind(load_profile(tmp_path, "comic-x")) == "comic"
