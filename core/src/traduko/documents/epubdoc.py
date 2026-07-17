"""EPUB parsing and repacking.

Reading goes through ebooklib (container/OPF/spine handling); writing
deliberately does not. Repacking copies the source zip entry by entry
and swaps only the chapters that actually carry translations, so every
untouched entry stays byte-identical and the output preserves mimetype
placement and compression choices.
"""
from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path

import ebooklib
from ebooklib import epub

from .htmldoc import ParsedHtml
from .model import Block, Chapter, DocumentDoc


def _opf_dir(source: Path) -> str:
    with zipfile.ZipFile(source) as zf:
        container = zf.read("META-INF/container.xml").decode("utf-8")
    # Minimal parse: the rootfile full-path attribute names the OPF.
    marker = 'full-path="'
    start = container.index(marker) + len(marker)
    opf_path = container[start : container.index('"', start)]
    return posixpath.dirname(opf_path)


def _entry_name(opf_dir: str, item_name: str) -> str:
    return posixpath.normpath(posixpath.join(opf_dir, item_name))


def parse_epub(path: Path) -> DocumentDoc:
    book = epub.read_epub(str(path))
    opf_dir = _opf_dir(path)
    spine_ids = [item_id for item_id, _linear in book.spine]
    chapters: list[Chapter] = []
    block_counter = 0
    for chapter_index, item_id in enumerate(spine_ids, start=1):
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        # The nav document is EPUB structure, not book content.
        if isinstance(item, epub.EpubNav) or "nav" in getattr(item, "properties", []):
            continue
        parsed = ParsedHtml(item.get_content())
        blocks: list[Block] = []
        for anchor, kind, text in parsed.blocks():
            block_counter += 1
            blocks.append(
                Block(
                    id=f"b-{block_counter:05d}",
                    kind=kind,
                    translate=True,
                    text=text,
                    anchor=anchor,
                )
            )
        chapters.append(
            Chapter(
                id=f"ch-{chapter_index:04d}",
                href=_entry_name(opf_dir, item.get_name()),
                blocks=blocks,
            )
        )
    return DocumentDoc(format="epub", chapters=chapters)


def repack_epub(
    source: Path,
    output: Path,
    doc: DocumentDoc,
    translations: dict[str, str],
) -> None:
    # Group anchor->text per chapter entry; chapters without translations
    # are copied through untouched.
    per_entry: dict[str, dict[str, str]] = {}
    for chapter in doc.chapters:
        chapter_map = {
            block.anchor: translations[block.id]
            for block in chapter.blocks
            if block.id in translations
        }
        if chapter_map:
            per_entry[chapter.href] = chapter_map

    with zipfile.ZipFile(source) as src, zipfile.ZipFile(output, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            entry = posixpath.normpath(info.filename)
            if entry in per_entry:
                parsed = ParsedHtml(data)
                parsed.apply(per_entry[entry])
                data = parsed.serialize().encode("utf-8")
            dst.writestr(info, data)
