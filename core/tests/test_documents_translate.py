import json
from pathlib import Path

import pytest

from traduko.budget import BudgetMeter
from traduko.config import CoreConfig
from traduko.documents.model import (
    Block,
    Chapter,
    Chunk,
    ChunksDoc,
    DocumentDoc,
    DocTranslationDoc,
    TranslatedChunk,
)
from traduko.documents.translate import (
    DocTranslationSettings,
    parse_chunk_response,
    translate_document_chunks,
)
from traduko.events import EventBus
from traduko.llm import create_llm
from traduko.prompts import DEFAULT_TEMPLATES
from traduko.translate import TranslationError


def test_parse_chunk_response_valid() -> None:
    content = 'noise [{"id": "b-1", "text": "one"}, {"id": "b-2", "text": "two"}] noise'
    assert parse_chunk_response(content, ["b-1", "b-2"]) == {
        "b-1": "one",
        "b-2": "two",
    }


def test_parse_chunk_response_rejects_id_mismatch() -> None:
    with pytest.raises(TranslationError):
        parse_chunk_response('[{"id": "b-1", "text": "one"}]', ["b-1", "b-2"])


def test_parse_chunk_response_rejects_non_array() -> None:
    with pytest.raises(TranslationError):
        parse_chunk_response("no array here", ["b-1"])


class RecordingProvider:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.prompts: list[str] = []

    def chat(self, request):
        self.prompts.append("\n".join(m.content for m in request.messages))
        return self.inner.chat(request)


def make_document(block_texts: list[str]) -> tuple[DocumentDoc, ChunksDoc]:
    """One chapter, one block per text, one chunk per two blocks."""
    blocks = [
        Block(id=f"b-{i + 1:05d}", kind="paragraph", translate=True, text=text)
        for i, text in enumerate(block_texts)
    ]
    document = DocumentDoc(
        format="txt", chapters=[Chapter(id="ch-0001", blocks=blocks)]
    )
    chunks = []
    for i in range(0, len(blocks), 2):
        group = blocks[i : i + 2]
        chunks.append(
            Chunk(
                id=f"c-{len(chunks) + 1:04d}",
                chapter_id="ch-0001",
                block_ids=[b.id for b in group],
                char_count=sum(len(b.text) for b in group),
            )
        )
    return document, ChunksDoc(chunks=chunks)


def response_for(ids_texts: dict[str, str]) -> str:
    return json.dumps([{"id": i, "text": t} for i, t in ids_texts.items()])


def run(
    tmp_path: Path,
    document: DocumentDoc,
    chunks: ChunksDoc,
    responses: list[str],
    settings: DocTranslationSettings | None = None,
    retry_ids: set[str] | None = None,
    prior: DocTranslationDoc | None = None,
):
    provider = RecordingProvider(
        create_llm({"type": "scripted", "responses": responses})
    )
    progress: list[tuple[int, int]] = []
    result = translate_document_chunks(
        document,
        chunks,
        settings
        or DocTranslationSettings(
            source_language="en", target_language="zh-TW", model="fake-model"
        ),
        provider,
        BudgetMeter(tmp_path, EventBus(), CoreConfig()),
        [],
        DEFAULT_TEMPLATES["doc-translate"],
        DEFAULT_TEMPLATES["doc-summary"],
        project="default",
        task_id="t-1",
        partial_path=tmp_path / "translation.partial.json",
        summary_path=tmp_path / "summary.json",
        emit_progress=lambda cur, total: progress.append((cur, total)),
        retry_ids=retry_ids,
        prior=prior,
    )
    return result, provider, progress


def test_translates_chunks_with_context_tail(tmp_path: Path) -> None:
    document, chunks = make_document(["one", "two", "three", "four"])
    responses = [
        response_for({"b-00001": "T1", "b-00002": "T2"}),
        response_for({"b-00003": "T3", "b-00004": "T4"}),
    ]
    result, provider, progress = run(tmp_path, document, chunks, responses)
    assert [c.status for c in result.chunks] == ["translated", "translated"]
    assert [b.text for b in result.chunks[1].blocks] == ["T3", "T4"]
    # Second chunk prompt carries the first chunk's translated tail.
    assert "T1" in provider.prompts[1] and "T2" in provider.prompts[1]
    assert progress == [(0, 2), (1, 2), (2, 2)]
    partial = json.loads(
        (tmp_path / "translation.partial.json").read_text(encoding="utf-8")
    )
    assert [c["id"] for c in partial] == ["c-0001", "c-0002"]


def test_bad_response_recovers_via_correction_retry(tmp_path: Path) -> None:
    document, chunks = make_document(["one", "two"])
    responses = ["garbage", response_for({"b-00001": "T1", "b-00002": "T2"})]
    result, provider, _ = run(tmp_path, document, chunks, responses)
    assert result.chunks[0].status == "translated"
    assert len(provider.prompts) == 2
    assert "Return only the JSON array" in provider.prompts[1]


def test_persistent_failure_bisects_down_to_single_blocks(tmp_path: Path) -> None:
    document, chunks = make_document(["one", "two"])
    responses = [
        "garbage",
        "still garbage",
        response_for({"b-00001": "T1"}),
        response_for({"b-00002": "T2"}),
    ]
    result, provider, _ = run(tmp_path, document, chunks, responses)
    assert result.chunks[0].status == "translated"
    assert [b.text for b in result.chunks[0].blocks] == ["T1", "T2"]
    assert len(provider.prompts) == 4


def test_single_block_failure_marks_chunk_failed_and_continues(tmp_path: Path) -> None:
    document, chunks = make_document(["one", "two", "three"])
    responses = [
        "garbage",
        "still garbage",  # full chunk fails twice -> bisect
        "garbage",
        "still garbage",  # single block b-00001 fails twice -> chunk failed
        response_for({"b-00003": "T3"}),
    ]
    result, provider, _ = run(tmp_path, document, chunks, responses)
    assert result.chunks[0].status == "failed"
    assert result.chunks[0].blocks == []
    assert result.chunks[1].status == "translated"


def test_resume_skips_chunks_already_in_partial(tmp_path: Path) -> None:
    document, chunks = make_document(["one", "two", "three", "four"])
    done = TranslatedChunk(
        id="c-0001",
        status="translated",
        blocks=[{"id": "b-00001", "text": "OLD1"}, {"id": "b-00002", "text": "OLD2"}],
    )
    (tmp_path / "translation.partial.json").write_text(
        json.dumps([done.model_dump()]), encoding="utf-8"
    )
    responses = [response_for({"b-00003": "T3", "b-00004": "T4"})]
    result, provider, _ = run(tmp_path, document, chunks, responses)
    assert [b.text for b in result.chunks[0].blocks] == ["OLD1", "OLD2"]
    assert [b.text for b in result.chunks[1].blocks] == ["T3", "T4"]
    assert len(provider.prompts) == 1


def test_summary_updates_after_chunk_threshold(tmp_path: Path) -> None:
    document, chunks = make_document(["one", "two", "three", "four", "five", "six"])
    settings = DocTranslationSettings(
        source_language="en",
        target_language="zh-TW",
        model="fake-model",
        summary_chunks=2,
    )
    responses = [
        response_for({"b-00001": "T1", "b-00002": "T2"}),
        response_for({"b-00003": "T3", "b-00004": "T4"}),
        "A summary.",
        response_for({"b-00005": "T5", "b-00006": "T6"}),
    ]
    result, provider, _ = run(tmp_path, document, chunks, responses, settings)
    assert [c.status for c in result.chunks] == ["translated"] * 3
    # Summary prompt saw both chunks' text; third chunk prompt saw the summary.
    assert "T1" in provider.prompts[2] and "T4" in provider.prompts[2]
    assert "A summary." in provider.prompts[3]
    state = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert state["schema_version"] == 1
    assert state["summary"] == "A summary."
    assert state["chunks_since"] == 1  # third chunk counted after the update
    assert "T5" in state["recent"]


def test_summary_updates_after_char_threshold(tmp_path: Path) -> None:
    document, chunks = make_document(["one", "two"])
    settings = DocTranslationSettings(
        source_language="en",
        target_language="zh-TW",
        model="fake-model",
        summary_chars=1,
    )
    responses = [
        response_for({"b-00001": "T1", "b-00002": "T2"}),
        "A summary.",
    ]
    run(tmp_path, document, chunks, responses, settings)
    state = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert state["summary"] == "A summary."
    assert state["recent"] == ""


def test_retry_ids_translates_only_flagged_and_carries_prior(tmp_path: Path) -> None:
    document, chunks = make_document(["one", "two", "three", "four"])
    prior = DocTranslationDoc(
        chunks=[
            TranslatedChunk(
                id="c-0001",
                status="translated",
                blocks=[
                    {"id": "b-00001", "text": "OLD1"},
                    {"id": "b-00002", "text": "OLD2"},
                ],
            ),
            TranslatedChunk(id="c-0002", status="failed", blocks=[]),
        ]
    )
    responses = [response_for({"b-00003": "NEW3", "b-00004": "NEW4"})]
    result, provider, _ = run(
        tmp_path, document, chunks, responses, retry_ids={"c-0002"}, prior=prior
    )
    assert [b.text for b in result.chunks[0].blocks] == ["OLD1", "OLD2"]
    assert result.chunks[1].status == "translated"
    assert [b.text for b in result.chunks[1].blocks] == ["NEW3", "NEW4"]
    assert len(provider.prompts) == 1
    # Retry context comes from the carried prior chunk's tail.
    assert "OLD2" in provider.prompts[0]
