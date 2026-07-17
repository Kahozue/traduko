import pytest
from pydantic import ValidationError

from traduko.documents.model import (
    Block,
    Chapter,
    ChunksDoc,
    DocumentDoc,
    DocTranslationDoc,
    QcDoc,
    QcFlag,
    TranslatedChunk,
)


def test_document_doc_roundtrip() -> None:
    doc = DocumentDoc(
        format="markdown",
        chapters=[
            Chapter(
                id="ch-001",
                title="One",
                blocks=[
                    Block(id="b-0001", kind="heading", translate=True, text="# One"),
                    Block(id="b-0002", kind="blank", translate=False, text="\n\n"),
                ],
            )
        ],
    )
    data = doc.model_dump()
    assert data["schema_version"] == 1
    again = DocumentDoc.model_validate(data)
    assert again == doc


def test_block_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        Block(id="b-1", kind="poem", translate=True, text="x")


def test_chapter_defaults() -> None:
    chapter = Chapter(id="ch-001", blocks=[])
    assert chapter.title == ""
    assert chapter.href == ""


def test_chunks_doc_roundtrip() -> None:
    doc = ChunksDoc.model_validate(
        {
            "chunks": [
                {
                    "id": "c-0001",
                    "chapter_id": "ch-001",
                    "block_ids": ["b-0001", "b-0003"],
                    "char_count": 42,
                }
            ]
        }
    )
    assert doc.schema_version == 1
    assert doc.chunks[0].block_ids == ["b-0001", "b-0003"]


def test_translation_doc_status_literal() -> None:
    doc = DocTranslationDoc(
        chunks=[
            TranslatedChunk(
                id="c-0001",
                status="translated",
                blocks=[{"id": "b-0001", "text": "translated text"}],
            )
        ]
    )
    assert doc.chunks[0].blocks[0].text == "translated text"
    with pytest.raises(ValidationError):
        TranslatedChunk(id="c-0002", status="skipped", blocks=[])


def test_qc_doc_roundtrip() -> None:
    doc = QcDoc(
        flags=[
            QcFlag(chunk_id="c-0001", block_id="b-0001", type="untranslated"),
            QcFlag(chunk_id="c-0002", type="echo", evidence="ratio 0.99"),
        ]
    )
    data = doc.model_dump()
    assert data["schema_version"] == 1
    assert data["flags"][1]["block_id"] == ""
    assert QcDoc.model_validate(data) == doc


def test_qc_flag_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        QcFlag(chunk_id="c-0001", type="spelling")
