"""Rule-based quality checks for document translations. No LLM calls.

Detections: chunks that never got a translation (status failed or
pending), untranslated blocks (normalized match or high similarity),
echoed chunks (whole batch nearly identical to source), and glossary
violations. When the target is Chinese, kanji-only source text is exempt
from the untranslated check: without hiragana there is no cheap way to
tell Japanese from a valid Chinese translation.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..glossary import GlossaryEntry
from .model import ChunksDoc, DocTranslationDoc, DocumentDoc, QcDoc, QcFlag

UNTRANSLATED_RATIO = 0.96
ECHO_RATIO = 0.98

_WS_RE = re.compile(r"\s+")
_HIRAGANA_RE = re.compile(r"[぀-ゟ]")
_CJK_RE = re.compile(r"[一-鿿]")


def normalize(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().casefold()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def is_untranslated(source: str, target: str, target_language: str) -> bool:
    s = normalize(source)
    t = normalize(target)
    if not s or not t:
        return False
    if (
        target_language.startswith("zh")
        and _CJK_RE.search(source)
        and len(_HIRAGANA_RE.findall(source)) < 2
    ):
        return False
    return s == t or similarity(s, t) >= UNTRANSLATED_RATIO


def is_echo(source_text: str, target_text: str) -> bool:
    s = normalize(source_text)
    t = normalize(target_text)
    if not s or not t:
        return False
    return similarity(s, t) >= ECHO_RATIO


def glossary_violations(
    source: str, target: str, entries: list[GlossaryEntry]
) -> list[GlossaryEntry]:
    return [e for e in entries if e.source in source and e.target not in target]


def scan(
    document: DocumentDoc,
    chunks: ChunksDoc,
    translation: DocTranslationDoc,
    glossary: list[GlossaryEntry],
    target_language: str,
) -> QcDoc:
    sources = {
        block.id: block.text
        for chapter in document.chapters
        for block in chapter.blocks
    }
    block_ids = {chunk.id: chunk.block_ids for chunk in chunks.chunks}
    flags: list[QcFlag] = []
    for chunk in translation.chunks:
        if chunk.status != "translated":
            flags.append(
                QcFlag(
                    chunk_id=chunk.id,
                    type="failed",
                    evidence=f"chunk has no translation (status: {chunk.status})",
                )
            )
            continue
        targets = {block.id: block.text for block in chunk.blocks}
        source_join = "\n".join(sources.get(i, "") for i in block_ids.get(chunk.id, []))
        target_join = "\n".join(targets.get(i, "") for i in block_ids.get(chunk.id, []))
        if is_echo(source_join, target_join):
            flags.append(
                QcFlag(chunk_id=chunk.id, type="echo", evidence="chunk echoes source")
            )
            continue
        for block_id in block_ids.get(chunk.id, []):
            source = sources.get(block_id, "")
            target = targets.get(block_id, "")
            if is_untranslated(source, target, target_language):
                flags.append(
                    QcFlag(
                        chunk_id=chunk.id,
                        block_id=block_id,
                        type="untranslated",
                        evidence=f"target matches source: {target[:80]!r}",
                    )
                )
                continue
            for entry in glossary_violations(source, target, glossary):
                flags.append(
                    QcFlag(
                        chunk_id=chunk.id,
                        block_id=block_id,
                        type="glossary",
                        evidence=f"{entry.source} -> {entry.target} not applied",
                    )
                )
    return QcDoc(flags=flags)
