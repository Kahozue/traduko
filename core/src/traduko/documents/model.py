"""Document pipeline data models.

These are the public shapes of the document pipeline artifacts
(document.json, chunks.json, and the document translation.json).
JSON Schema copies live in docs/schemas/.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BlockKind = Literal["heading", "paragraph", "code", "blank", "other"]
ChunkStatus = Literal["translated", "failed", "pending"]
QcFlagType = Literal["untranslated", "echo", "glossary", "failed"]

DocumentFormat = Literal["markdown", "txt", "html", "epub"]


class Block(BaseModel):
    id: str
    kind: BlockKind
    translate: bool
    text: str
    anchor: str = ""


class Chapter(BaseModel):
    id: str
    title: str = ""
    href: str = ""
    blocks: list[Block] = Field(default_factory=list)


class DocumentDoc(BaseModel):
    schema_version: int = 1
    format: DocumentFormat
    chapters: list[Chapter] = Field(default_factory=list)


class Chunk(BaseModel):
    id: str
    chapter_id: str
    block_ids: list[str] = Field(default_factory=list)
    char_count: int = 0


class ChunksDoc(BaseModel):
    schema_version: int = 1
    chunks: list[Chunk] = Field(default_factory=list)


class TranslatedBlock(BaseModel):
    id: str
    text: str


class TranslatedChunk(BaseModel):
    id: str
    status: ChunkStatus
    blocks: list[TranslatedBlock] = Field(default_factory=list)


class DocTranslationDoc(BaseModel):
    schema_version: int = 1
    chunks: list[TranslatedChunk] = Field(default_factory=list)


class QcFlag(BaseModel):
    chunk_id: str
    block_id: str = ""
    type: QcFlagType
    evidence: str = ""


class QcDoc(BaseModel):
    schema_version: int = 1
    flags: list[QcFlag] = Field(default_factory=list)
