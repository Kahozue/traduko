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


def test_doc_translate_template_renders() -> None:
    template = load_template(Path("/nonexistent"), "doc-translate")
    out = render(
        template,
        {
            "source_language": "en", "target_language": "zh-TW",
            "style": "terse",
            "glossary": "(none)", "summary": "(none)", "context": "(none)",
            "blocks_json": '[{"id": "b-00001", "text": "hello"}]',
        },
    )
    assert "BLOCKS:" in out
    assert '"b-00001"' in out
    assert "Style notes: terse" in out


def test_doc_summary_template_renders() -> None:
    template = load_template(Path("/nonexistent"), "doc-summary")
    out = render(
        template,
        {
            "target_language": "zh-TW",
            "summary": "(none)",
            "recent_text": "some translated text",
        },
    )
    assert "some translated text" in out
    assert "BLOCKS:" not in out


def test_proofread_template_renders() -> None:
    template = load_template(Path("/nonexistent"), "proofread")
    text = render(
        template,
        {
            "source_language": "en", "target_language": "eo",
            "total_segments": "5", "glossary": "(none)",
        },
    )
    assert "proofreader" in text and "5" in text


def test_glossary_proofread_template_renders() -> None:
    template = load_template(Path("/nonexistent"), "glossary_proofread")
    text = render(
        template,
        {
            "source_language": "zh-TW",
            "glossary": "Traduko -> 特拉杜科",
            "segments_json": '[{"id": 1, "text": "Traduko"}]',
        },
    )
    assert "transcription proofreader" in text
    assert "Traduko -> 特拉杜科" in text
