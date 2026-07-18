import tomllib
from pathlib import Path

import traduko


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"][
        "version"
    ]
    assert traduko.__version__ == expected


def test_profile_kind_explicit_and_audio_markers(tmp_path):
    from traduko.profiles import Profile, ProfileStage, profile_kind

    explicit = Profile(name="x", kind="audio", stages=[ProfileStage(type="noop")])
    assert profile_kind(explicit) == "audio"
    marker = Profile(
        name="y",
        stages=[ProfileStage(type="extract_audio"), ProfileStage(type="export_transcript")],
    )
    assert profile_kind(marker) == "audio"
    video = Profile(name="z", stages=[ProfileStage(type="extract_audio")])
    assert profile_kind(video) == "video"
