"""Markdown and plain-text parsing into translation blocks.

Custom line-based splitting instead of a markdown parser: every source
character lands in exactly one block, so joining the block texts
reproduces the input byte-for-byte. That construction is what makes the
no-translation round trip lossless.
"""
from __future__ import annotations

import re

from .model import Block, Chapter, DocumentDoc

_HEADING = re.compile(r"^#{1,6} ")


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def _fence_marker(line: str) -> str | None:
    for marker in ("```", "~~~"):
        if line.startswith(marker):
            return marker
    return None


def _split_blocks(text: str, markdown: bool) -> list[tuple[str, str]]:
    lines = text.splitlines(keepends=True)
    blocks: list[tuple[str, str]] = []
    buffer: list[str] = []
    buffer_kind = ""

    def flush() -> None:
        nonlocal buffer, buffer_kind
        if buffer:
            blocks.append((buffer_kind, "".join(buffer)))
            buffer = []
            buffer_kind = ""

    index = 0
    while index < len(lines):
        line = lines[index]
        marker = _fence_marker(line) if markdown else None
        if marker is not None:
            flush()
            fence = [line]
            index += 1
            while index < len(lines):
                fence.append(lines[index])
                closed = lines[index].startswith(marker)
                index += 1
                if closed:
                    break
            blocks.append(("code", "".join(fence)))
            continue
        if _is_blank(line):
            if buffer_kind != "blank":
                flush()
                buffer_kind = "blank"
            buffer.append(line)
        elif markdown and _HEADING.match(line):
            flush()
            blocks.append(("heading", line))
        else:
            if buffer_kind != "paragraph":
                flush()
                buffer_kind = "paragraph"
            buffer.append(line)
        index += 1
    flush()
    return blocks


def build_document(text: str, format: str) -> DocumentDoc:
    raw = _split_blocks(text, markdown=format == "markdown")
    blocks = [
        Block(
            id=f"b-{n:05d}",
            kind=kind,
            translate=kind in ("heading", "paragraph"),
            text=block_text,
        )
        for n, (kind, block_text) in enumerate(raw, start=1)
    ]
    return DocumentDoc(
        format=format,  # type: ignore[arg-type]
        chapters=[Chapter(id="ch-0001", blocks=blocks)],
    )


def serialize_document(doc: DocumentDoc, translations: dict[str, str]) -> str:
    parts: list[str] = []
    for chapter in doc.chapters:
        for block in chapter.blocks:
            if block.translate and block.id in translations:
                trailing = len(block.text) - len(block.text.rstrip("\n"))
                parts.append(translations[block.id].rstrip("\n") + "\n" * trailing)
            else:
                parts.append(block.text)
    return "".join(parts)
