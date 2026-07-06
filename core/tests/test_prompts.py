from pathlib import Path

import pytest

from traduko.prompts import DEFAULT_TEMPLATES, PromptError, load_template, render

VARS = {
    "source_language": "ja",
    "target_language": "zh-TW",
    "style": "(none)",
    "glossary": "(none)",
    "context": "(none)",
    "segments_json": '[{"id": 1, "text": "hello"}]',
}


def test_default_translate_template_renders() -> None:
    template = load_template(Path("/nonexistent"), "translate")
    out = render(template, VARS)
    assert "ja" in out and "zh-TW" in out
    assert "SEGMENTS:" in out
    assert '[{"id": 1, "text": "hello"}]' in out


def test_override_wins(tmp_path: Path) -> None:
    (tmp_path / "prompts").mkdir(parents=True)
    (tmp_path / "prompts" / "translate.txt").write_text(
        "custom ${target_language}\nSEGMENTS:\n${segments_json}\n", encoding="utf-8"
    )
    out = render(load_template(tmp_path, "translate"), VARS)
    assert out.startswith("custom zh-TW")


def test_unknown_template_raises(tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        load_template(tmp_path, "nope")


def test_missing_variable_raises() -> None:
    with pytest.raises(PromptError):
        render(DEFAULT_TEMPLATES["translate"], {"target_language": "en"})
