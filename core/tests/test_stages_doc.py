import json
from pathlib import Path

import pytest

from traduko.artifacts import ArtifactStore
from traduko.documents.epubdoc import parse_epub
from traduko.events import EventBus
from traduko.models import StageRecord, TaskRecord, utc_now_iso
from traduko.stages import base, registry

from test_documents_epub import make_epub


def make_ctx(
    tmp_path: Path,
    input_path: Path,
    stage_index: int = 0,
    params: dict | None = None,
):
    now = utc_now_iso()
    task = TaskRecord(
        id="t-doc",
        project="default",
        input_path=str(input_path),
        profile="novel",
        stages=[StageRecord(type="noop")],
        created_at=now,
        updated_at=now,
    )
    task_dir = tmp_path / "projects" / "default" / "tasks" / task.id
    progress: list[tuple[int, int]] = []
    ctx = base.StageContext(
        task=task,
        stage_index=stage_index,
        params=params or {},
        artifacts=ArtifactStore(task_dir),
        data_root=tmp_path,
        emit_progress=lambda cur, total: progress.append((cur, total)),
        should_cancel=lambda: False,
        bus=EventBus(),
    )
    return ctx, progress


MD = "# Title\n\nPara one.\n\nPara two.\n"


def test_ingest_markdown(tmp_path: Path) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    ctx, progress = make_ctx(tmp_path, src)
    result = registry.create("ingest_document").run(ctx)
    assert result.artifacts == ["01-document.json"]
    data = ctx.artifacts.read_latest_json("document.json")
    assert data["format"] == "markdown"
    texts = [b["text"] for b in data["chapters"][0]["blocks"]]
    assert "".join(texts) == MD
    assert progress[-1] == (1, 1)


def test_ingest_unknown_extension_fails(tmp_path: Path) -> None:
    src = tmp_path / "book.docx"
    src.write_text("x", encoding="utf-8")
    ctx, _ = make_ctx(tmp_path, src)
    with pytest.raises(base.StageError):
        registry.create("ingest_document").run(ctx)


def test_ingest_epub(tmp_path: Path) -> None:
    src = tmp_path / "book.epub"
    make_epub(src)
    ctx, _ = make_ctx(tmp_path, src)
    registry.create("ingest_document").run(ctx)
    data = ctx.artifacts.read_latest_json("document.json")
    assert data["format"] == "epub"
    assert len([c for c in data["chapters"] if c["blocks"]]) == 2


def _write_document(ctx, blocks_per_chapter: dict[str, list[dict]]) -> None:
    chapters = [
        {"id": chapter_id, "title": "", "href": "", "blocks": blocks}
        for chapter_id, blocks in blocks_per_chapter.items()
    ]
    ctx.artifacts.write_json(
        1, "document.json", {"format": "txt", "chapters": chapters}
    )


def _block(n: int, text: str, translate: bool = True) -> dict:
    return {
        "id": f"b-{n:05d}",
        "kind": "paragraph" if translate else "blank",
        "translate": translate,
        "text": text,
        "anchor": "",
    }


def test_chunk_grouping_respects_base_and_chapter_boundaries(tmp_path: Path) -> None:
    src = tmp_path / "book.txt"
    src.write_text("x", encoding="utf-8")
    ctx, _ = make_ctx(
        tmp_path,
        src,
        stage_index=1,
        params={"base_blocks": 2, "base_chars": 1000},
    )
    _write_document(
        ctx,
        {
            "ch-0001": [
                _block(1, "a" * 10),
                _block(2, "\n\n", translate=False),
                _block(3, "b" * 10),
                _block(4, "c" * 10),
            ],
            "ch-0002": [_block(5, "d" * 10)],
        },
    )
    registry.create("chunk").run(ctx)
    data = ctx.artifacts.read_latest_json("chunks.json")
    groups = [(c["chapter_id"], c["block_ids"]) for c in data["chunks"]]
    assert groups == [
        ("ch-0001", ["b-00001", "b-00003"]),
        ("ch-0001", ["b-00004"]),
        ("ch-0002", ["b-00005"]),
    ]
    assert data["chunks"][0]["char_count"] == 20


def test_chunk_char_limit_closes_before_overflow(tmp_path: Path) -> None:
    src = tmp_path / "book.txt"
    src.write_text("x", encoding="utf-8")
    ctx, _ = make_ctx(
        tmp_path,
        src,
        stage_index=1,
        params={"base_blocks": 10, "base_chars": 100, "max_chars": 120},
    )
    _write_document(
        ctx,
        {"ch-0001": [_block(1, "a" * 90), _block(2, "b" * 90), _block(3, "c" * 5)]},
    )
    registry.create("chunk").run(ctx)
    data = ctx.artifacts.read_latest_json("chunks.json")
    groups = [c["block_ids"] for c in data["chunks"]]
    assert groups == [["b-00001"], ["b-00002", "b-00003"]]


def test_export_without_translation_reproduces_source(tmp_path: Path) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    ingest_ctx, _ = make_ctx(tmp_path, src, stage_index=0)
    registry.create("ingest_document").run(ingest_ctx)
    export_ctx, _ = make_ctx(tmp_path, src, stage_index=2)
    result = registry.create("export_document").run(export_ctx)
    assert result.artifacts == ["03-translated.md"]
    out = export_ctx.artifacts.path_for(3, "translated.md")
    assert out.read_text(encoding="utf-8") == MD


def test_export_applies_translated_chunks_only(tmp_path: Path) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    ctx, _ = make_ctx(tmp_path, src, stage_index=0)
    registry.create("ingest_document").run(ctx)
    doc = ctx.artifacts.read_latest_json("document.json")
    blocks = doc["chapters"][0]["blocks"]
    para_one = next(b for b in blocks if b["text"].startswith("Para one"))
    para_two = next(b for b in blocks if b["text"].startswith("Para two"))
    ctx.artifacts.write_json(
        2,
        "translation.json",
        {
            "chunks": [
                {
                    "id": "c-0001",
                    "status": "translated",
                    "blocks": [{"id": para_one["id"], "text": "First translated."}],
                },
                {
                    "id": "c-0002",
                    "status": "failed",
                    "blocks": [{"id": para_two["id"], "text": "MUST NOT APPEAR"}],
                },
            ]
        },
    )
    export_ctx, _ = make_ctx(tmp_path, src, stage_index=2)
    registry.create("export_document").run(export_ctx)
    out = export_ctx.artifacts.path_for(3, "translated.md").read_text(encoding="utf-8")
    assert out == "# Title\n\nFirst translated.\n\nPara two.\n"


def test_export_epub_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "book.epub"
    make_epub(src)
    ctx, _ = make_ctx(tmp_path, src, stage_index=0)
    registry.create("ingest_document").run(ctx)
    doc = ctx.artifacts.read_latest_json("document.json")
    first_para = next(
        b
        for c in doc["chapters"]
        for b in c["blocks"]
        if b["text"] == "First paragraph."
    )
    ctx.artifacts.write_json(
        2,
        "translation.json",
        {
            "chunks": [
                {
                    "id": "c-0001",
                    "status": "translated",
                    "blocks": [{"id": first_para["id"], "text": "Translated para."}],
                }
            ]
        },
    )
    export_ctx, _ = make_ctx(tmp_path, src, stage_index=2)
    result = registry.create("export_document").run(export_ctx)
    assert result.artifacts == ["03-translated.epub"]
    out_doc = parse_epub(export_ctx.artifacts.path_for(3, "translated.epub"))
    texts = [b.text for c in out_doc.chapters for b in c.blocks]
    assert "Translated para." in texts
    assert "First paragraph." not in texts
    assert "Second paragraph." in texts


def test_export_html_applies_translation(tmp_path: Path) -> None:
    src = tmp_path / "page.html"
    src.write_text(
        "<html><body><p>Hello world.</p><p>Keep me.</p></body></html>",
        encoding="utf-8",
    )
    ctx, _ = make_ctx(tmp_path, src, stage_index=0)
    registry.create("ingest_document").run(ctx)
    doc = ctx.artifacts.read_latest_json("document.json")
    hello = doc["chapters"][0]["blocks"][0]
    ctx.artifacts.write_json(
        2,
        "translation.json",
        {
            "chunks": [
                {
                    "id": "c-0001",
                    "status": "translated",
                    "blocks": [{"id": hello["id"], "text": "Translated hello."}],
                }
            ]
        },
    )
    export_ctx, _ = make_ctx(tmp_path, src, stage_index=2)
    registry.create("export_document").run(export_ctx)
    out = export_ctx.artifacts.path_for(3, "translated.html").read_text(
        encoding="utf-8"
    )
    assert "Translated hello." in out
    assert "Keep me." in out
