from traduko.documents.markdown import build_document, serialize_document

SAMPLE = """# Title

First paragraph
spans two lines.

```python
# not a heading
code()
```

## Section

Last paragraph without trailing newline"""


def joined(doc) -> str:
    return "".join(b.text for b in doc.chapters[0].blocks)


def test_markdown_kinds() -> None:
    doc = build_document(SAMPLE, "markdown")
    kinds = [b.kind for b in doc.chapters[0].blocks]
    assert kinds == [
        "heading",
        "blank",
        "paragraph",
        "blank",
        "code",
        "blank",
        "heading",
        "blank",
        "paragraph",
    ]
    code = doc.chapters[0].blocks[4]
    assert code.translate is False
    assert code.text.startswith("```python\n")
    assert "# not a heading" in code.text


def test_markdown_byte_roundtrip() -> None:
    for text in (
        SAMPLE,
        "no newline at end",
        "trailing newlines\n\n\n",
        "\n\nleading blanks\n",
        "# only a heading\n",
        "para\n```\nunclosed fence\n",
    ):
        doc = build_document(text, "markdown")
        assert joined(doc) == text
        assert serialize_document(doc, {}) == text


def test_heading_requires_space() -> None:
    doc = build_document("#tag line\n", "markdown")
    assert doc.chapters[0].blocks[0].kind == "paragraph"


def test_txt_has_no_heading_or_fence() -> None:
    doc = build_document("# looks like heading\n\n```\nfence?\n```\n", "txt")
    kinds = [b.kind for b in doc.chapters[0].blocks]
    assert "heading" not in kinds
    assert "code" not in kinds


def test_block_ids_are_stable_and_unique() -> None:
    doc = build_document(SAMPLE, "markdown")
    ids = [b.id for b in doc.chapters[0].blocks]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids)


def test_serialize_with_translation_keeps_trailing_newlines() -> None:
    doc = build_document("First para.\n\nSecond para.\n", "markdown")
    blocks = doc.chapters[0].blocks
    first = blocks[0]
    out = serialize_document(doc, {first.id: "Translated."})
    assert out == "Translated.\n\nSecond para.\n"


def test_serialize_translation_strips_extra_newlines() -> None:
    doc = build_document("Para one.\n\nPara two.\n", "markdown")
    first = doc.chapters[0].blocks[0]
    out = serialize_document(doc, {first.id: "Translated.\n\n\n"})
    assert out == "Translated.\n\nPara two.\n"


def test_blank_blocks_never_translate() -> None:
    doc = build_document(SAMPLE, "markdown")
    for block in doc.chapters[0].blocks:
        if block.kind == "blank":
            assert block.translate is False
