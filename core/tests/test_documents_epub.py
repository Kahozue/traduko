import zipfile
from pathlib import Path

from ebooklib import epub

from traduko.documents.epubdoc import parse_epub, repack_epub

CH1 = (
    "<html><head><title>c1</title></head><body>"
    "<h1>Chapter One</h1><p>First paragraph.</p><p>Second paragraph.</p>"
    "</body></html>"
)
CH2 = (
    "<html><head><title>c2</title></head><body>"
    "<h1>Chapter Two</h1><p>Another paragraph.</p>"
    "</body></html>"
)


def make_epub(path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("test-book")
    book.set_title("Test Book")
    book.set_language("en")
    one = epub.EpubHtml(title="One", file_name="ch1.xhtml", content=CH1)
    two = epub.EpubHtml(title="Two", file_name="ch2.xhtml", content=CH2)
    book.add_item(one)
    book.add_item(two)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", one, two]
    epub.write_epub(str(path), book)


def entry_bytes(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def test_parse_epub_chapters_and_blocks(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    make_epub(source)
    doc = parse_epub(source)
    first = next(ch for ch in doc.chapters if ch.href.endswith("ch1.xhtml"))
    assert [b.text for b in first.blocks] == [
        "Chapter One",
        "First paragraph.",
        "Second paragraph.",
    ]
    assert [b.kind for b in first.blocks] == ["heading", "paragraph", "paragraph"]
    ids = [b.id for ch in doc.chapters for b in ch.blocks]
    assert len(ids) == len(set(ids))
    all_texts = [b.text for ch in doc.chapters for b in ch.blocks]
    assert "Test Book" not in all_texts


def test_untranslated_repack_is_byte_identical_per_entry(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    output = tmp_path / "out.epub"
    make_epub(source)
    doc = parse_epub(source)
    repack_epub(source, output, doc, {})
    before = entry_bytes(source)
    after = entry_bytes(output)
    assert before.keys() == after.keys()
    for name in before:
        assert after[name] == before[name], name


def test_translated_repack_replaces_only_target_chapter(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    output = tmp_path / "out.epub"
    make_epub(source)
    doc = parse_epub(source)
    target = next(ch for ch in doc.chapters if ch.href.endswith("ch1.xhtml"))
    first_para = target.blocks[1]
    repack_epub(source, output, doc, {first_para.id: "Translated text."})

    out_doc = parse_epub(output)
    out_target = next(ch for ch in out_doc.chapters if ch.href.endswith("ch1.xhtml"))
    assert [b.text for b in out_target.blocks] == [
        "Chapter One",
        "Translated text.",
        "Second paragraph.",
    ]

    before = entry_bytes(source)
    after = entry_bytes(output)
    changed = [name for name in before if after[name] != before[name]]
    assert changed == [n for n in before if n.endswith("ch1.xhtml")]
