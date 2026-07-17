from traduko.documents.htmldoc import ParsedHtml

SAMPLE = """<html><head><meta charset="utf-8"><title>t</title></head><body>
<h2 id="s1">Section <em>one</em></h2>
<p class="lead">First <strong>paragraph</strong> here.</p>
<blockquote><p>Nested quote text.</p></blockquote>
<ul><li>Item one</li><li>Item two</li></ul>
<p>   </p>
</body></html>"""


def test_block_extraction_flattens_inline_and_skips_empty() -> None:
    parsed = ParsedHtml(SAMPLE)
    blocks = parsed.blocks()
    texts = [text for _, _, text in blocks]
    kinds = [kind for _, kind, _ in blocks]
    assert texts == [
        "Section one",
        "First paragraph here.",
        "Nested quote text.",
        "Item one",
        "Item two",
    ]
    assert kinds == ["heading", "paragraph", "paragraph", "paragraph", "paragraph"]


def test_nested_block_not_duplicated() -> None:
    parsed = ParsedHtml(SAMPLE)
    texts = [text for _, _, text in parsed.blocks()]
    assert texts.count("Nested quote text.") == 1


def test_apply_translation_keeps_attributes() -> None:
    parsed = ParsedHtml(SAMPLE)
    blocks = parsed.blocks()
    anchor = blocks[1][0]
    parsed.apply({anchor: "Translated paragraph."})
    out = parsed.serialize()
    reparsed = ParsedHtml(out)
    texts = [text for _, _, text in reparsed.blocks()]
    assert texts[1] == "Translated paragraph."
    assert 'class="lead"' in out
    assert "Section one" in texts


def test_untranslated_roundtrip_preserves_text_sequence() -> None:
    parsed = ParsedHtml(SAMPLE)
    original = [text for _, _, text in parsed.blocks()]
    out = ParsedHtml(parsed.serialize())
    assert [text for _, _, text in out.blocks()] == original


def test_non_utf8_charset_is_decoded_and_normalized() -> None:
    big5 = (
        "<html><head><meta charset=\"big5\"></head><body>"
        "<p>翻譯測試</p></body></html>"
    ).encode("big5")
    parsed = ParsedHtml(big5)
    texts = [text for _, _, text in parsed.blocks()]
    assert texts == ["翻譯測試"]
    out = parsed.serialize()
    assert "big5" not in out.lower()
    assert 'charset="utf-8"' in out.lower().replace("'", '"')
