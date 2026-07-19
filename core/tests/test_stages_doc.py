from pathlib import Path

import pytest

from traduko.artifacts import ArtifactStore
from traduko.config import CoreConfig, save_config
from traduko.documents.epubdoc import parse_epub
from traduko.documents.model import ChunksDoc
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


def _ingest_and_chunk(tmp_path: Path, src: Path) -> None:
    ingest_ctx, _ = make_ctx(tmp_path, src, stage_index=0)
    registry.create("ingest_document").run(ingest_ctx)
    chunk_ctx, _ = make_ctx(tmp_path, src, stage_index=1)
    registry.create("chunk").run(chunk_ctx)


def test_translate_chunks_with_fake_provider(tmp_path: Path) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    _ingest_and_chunk(tmp_path, src)
    ctx, progress = make_ctx(
        tmp_path, src, stage_index=2, params={"target_language": "en"}
    )
    result = registry.create("translate_chunks").run(ctx)
    assert "03-translation.json" in result.artifacts
    assert "03-translation.partial.json" in result.artifacts
    data = ctx.artifacts.read_latest_json("translation.json")
    assert data["schema_version"] == 1
    texts = [b["text"] for c in data["chunks"] for b in c["blocks"]]
    assert texts and all(t.startswith("[T] ") for t in texts)
    assert all(c["status"] == "translated" for c in data["chunks"])
    assert progress[-1][0] == progress[-1][1]


def test_translate_chunks_requires_target_language(tmp_path: Path) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    _ingest_and_chunk(tmp_path, src)
    ctx, _ = make_ctx(tmp_path, src, stage_index=2)
    with pytest.raises(base.StageError):
        registry.create("translate_chunks").run(ctx)


def test_translate_chunks_only_flagged_requires_prior_artifacts(tmp_path: Path) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    _ingest_and_chunk(tmp_path, src)
    ctx, _ = make_ctx(
        tmp_path,
        src,
        stage_index=2,
        params={"target_language": "en", "only_flagged": True},
    )
    with pytest.raises(base.StageError):
        registry.create("translate_chunks").run(ctx)


def test_translate_chunks_only_flagged_noop_when_clean(tmp_path: Path) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    _ingest_and_chunk(tmp_path, src)
    first_ctx, _ = make_ctx(
        tmp_path, src, stage_index=2, params={"target_language": "en"}
    )
    registry.create("translate_chunks").run(first_ctx)
    qc_ctx, _ = make_ctx(
        tmp_path, src, stage_index=3, params={"target_language": "en"}
    )
    registry.create("qc_scan").run(qc_ctx)
    retry_ctx, _ = make_ctx(
        tmp_path,
        src,
        stage_index=4,
        params={"target_language": "en", "only_flagged": True},
    )
    result = registry.create("translate_chunks").run(retry_ctx)
    assert result.artifacts == []
    # Latest translation is still the first round's artifact.
    latest = retry_ctx.artifacts.latest_path("translation.json")
    assert latest.name == "03-translation.json"


def test_translate_chunks_only_flagged_retranslates_failed_chunks(tmp_path: Path) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    _ingest_and_chunk(tmp_path, src)
    chunks = ChunksDoc.model_validate(
        make_ctx(tmp_path, src)[0].artifacts.read_latest_json("chunks.json")
    )
    setup_ctx, _ = make_ctx(tmp_path, src, stage_index=2)
    setup_ctx.artifacts.write_json(
        3,
        "translation.json",
        {
            "chunks": [
                {"id": chunk.id, "status": "failed", "blocks": []}
                for chunk in chunks.chunks
            ]
        },
    )
    setup_ctx.artifacts.write_json(4, "qc.json", {"flags": []})
    retry_ctx, _ = make_ctx(
        tmp_path,
        src,
        stage_index=4,
        params={"target_language": "en", "only_flagged": True},
    )
    result = registry.create("translate_chunks").run(retry_ctx)
    assert "05-translation.json" in result.artifacts
    data = retry_ctx.artifacts.read_latest_json("translation.json")
    assert all(c["status"] == "translated" for c in data["chunks"])


def test_translate_chunks_retry_round_fails_when_chunks_stay_failed(
    tmp_path: Path,
) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    _ingest_and_chunk(tmp_path, src)
    save_config(
        tmp_path,
        CoreConfig(
            default_provider="bad",
            llm_providers={
                "bad": {"type": "scripted", "responses": ["not json"] * 12}
            },
        ),
    )
    chunks = ChunksDoc.model_validate(
        make_ctx(tmp_path, src)[0].artifacts.read_latest_json("chunks.json")
    )
    setup_ctx, _ = make_ctx(tmp_path, src, stage_index=2)
    setup_ctx.artifacts.write_json(
        3,
        "translation.json",
        {
            "chunks": [
                {"id": chunk.id, "status": "failed", "blocks": []}
                for chunk in chunks.chunks
            ]
        },
    )
    setup_ctx.artifacts.write_json(4, "qc.json", {"flags": []})
    retry_ctx, _ = make_ctx(
        tmp_path,
        src,
        stage_index=4,
        params={"target_language": "en", "only_flagged": True},
    )
    with pytest.raises(base.StageError, match="1 of 1 chunks failed"):
        registry.create("translate_chunks").run(retry_ctx)
    # State is persisted before the gate raises, so the editor and a
    # later resume see the failed chunks.
    data = retry_ctx.artifacts.read_latest_json("translation.json")
    assert all(c["status"] == "failed" for c in data["chunks"])


def test_qc_scan_requires_translation(tmp_path: Path) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    _ingest_and_chunk(tmp_path, src)
    ctx, _ = make_ctx(tmp_path, src, stage_index=3)
    with pytest.raises(base.StageError):
        registry.create("qc_scan").run(ctx)


def test_qc_scan_flags_echoed_translation(tmp_path: Path) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    _ingest_and_chunk(tmp_path, src)
    ctx, _ = make_ctx(
        tmp_path, src, stage_index=3, params={"target_language": "en"}
    )
    document = ctx.artifacts.read_latest_json("document.json")
    sources = {
        b["id"]: b["text"]
        for c in document["chapters"]
        for b in c["blocks"]
    }
    chunks = ctx.artifacts.read_latest_json("chunks.json")
    ctx.artifacts.write_json(
        3,
        "translation.json",
        {
            "chunks": [
                {
                    "id": chunk["id"],
                    "status": "translated",
                    "blocks": [
                        {"id": i, "text": sources[i]} for i in chunk["block_ids"]
                    ],
                }
                for chunk in chunks["chunks"]
            ]
        },
    )
    result = registry.create("qc_scan").run(ctx)
    assert result.artifacts == ["04-qc.json"]
    qc = ctx.artifacts.read_latest_json("qc.json")
    assert qc["flags"]
    assert all(f["type"] in ("echo", "untranslated") for f in qc["flags"])


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


def test_export_fails_when_chunks_are_not_translated(tmp_path: Path) -> None:
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
    with pytest.raises(base.StageError, match="1 of 2 chunks"):
        registry.create("export_document").run(export_ctx)
    assert not export_ctx.artifacts.path_for(3, "translated.md").exists()


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


def test_translate_chunks_prompt_override_bypasses_template_file(
    tmp_path: Path,
) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    _ingest_and_chunk(tmp_path, src)
    prompts = tmp_path / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    (prompts / "doc-translate.txt").write_text("${no_such_variable}", encoding="utf-8")
    ctx, _ = make_ctx(
        tmp_path,
        src,
        stage_index=2,
        params={
            "target_language": "en",
            "prompt_override": "To ${target_language}: ${blocks_json}",
        },
    )

    result = registry.create("translate_chunks").run(ctx)

    assert "03-translation.json" in result.artifacts


def test_translate_chunks_prompt_override_missing_variable_names_the_override(
    tmp_path: Path,
) -> None:
    src = tmp_path / "book.md"
    src.write_text(MD, encoding="utf-8")
    _ingest_and_chunk(tmp_path, src)
    ctx, _ = make_ctx(
        tmp_path,
        src,
        stage_index=2,
        params={"target_language": "en", "prompt_override": "${no_such_variable}"},
    )

    with pytest.raises(base.StageError) as error:
        registry.create("translate_chunks").run(ctx)

    assert "prompt override" in str(error.value).lower()
