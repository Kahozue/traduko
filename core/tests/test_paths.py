from pathlib import Path

from translator_core.paths import ENV_DATA_ROOT, SUBDIRS, ensure_layout, resolve_data_root


def test_explicit_root_wins_over_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(ENV_DATA_ROOT, str(tmp_path / "from-env"))
    assert resolve_data_root(tmp_path / "explicit") == tmp_path / "explicit"


def test_env_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(ENV_DATA_ROOT, str(tmp_path / "from-env"))
    assert resolve_data_root() == tmp_path / "from-env"


def test_ensure_layout_creates_subdirs(tmp_path: Path) -> None:
    ensure_layout(tmp_path)
    for sub in SUBDIRS:
        assert (tmp_path / sub).is_dir()
