"""HTML block extraction and write-back, shared by the html and epub formats.

Blocks are the deepest block-level elements with any text; anchors are
XPaths, which are deterministic for a given input so re-parsing the same
source always yields matching anchors. Applying a translation replaces
the element's whole text content (inline markup inside translated blocks
is flattened by design; untouched elements keep their bytes semantics).
"""
from __future__ import annotations

import lxml.html

from .model import Block, Chapter, DocumentDoc

BLOCK_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "th",
    "td",
    "blockquote",
    "figcaption",
    "dt",
    "dd",
}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class ParsedHtml:
    def __init__(self, content: bytes | str) -> None:
        if isinstance(content, str):
            self.root = lxml.html.fromstring(content)
        else:
            # lxml honours the declared charset when given raw bytes.
            self.root = lxml.html.document_fromstring(content)
        self.tree = self.root.getroottree()

    def blocks(self) -> list[tuple[str, str, str]]:
        found: list[tuple[str, str, str]] = []
        for element in self.root.iter():
            if not isinstance(element.tag, str) or element.tag not in BLOCK_TAGS:
                continue
            if any(
                isinstance(child.tag, str) and child.tag in BLOCK_TAGS
                for child in element.iterdescendants()
            ):
                continue
            text = element.text_content().strip()
            if not text:
                continue
            kind = "heading" if element.tag in _HEADINGS else "paragraph"
            found.append((self.tree.getpath(element), kind, text))
        return found

    def apply(self, translations: dict[str, str]) -> None:
        for anchor, text in translations.items():
            hits = self.tree.xpath(anchor)
            if not hits:
                continue
            element = hits[0]
            for child in list(element):
                element.remove(child)
            element.text = text

    def serialize(self) -> str:
        for meta in self.root.xpath("//meta[@charset]"):
            meta.set("charset", "utf-8")
        for meta in self.root.xpath(
            "//meta[translate(@http-equiv,'CONTENT-TYPE','content-type')"
            "='content-type']"
        ):
            meta.set("content", "text/html; charset=utf-8")
        return lxml.html.tostring(self.root, encoding="unicode")


def build_html_document(content: bytes | str) -> DocumentDoc:
    parsed = ParsedHtml(content)
    blocks = [
        Block(id=f"b-{n:05d}", kind=kind, translate=True, text=text, anchor=anchor)
        for n, (anchor, kind, text) in enumerate(parsed.blocks(), start=1)
    ]
    return DocumentDoc(format="html", chapters=[Chapter(id="ch-0001", blocks=blocks)])
