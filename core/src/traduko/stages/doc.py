"""Document pipeline stages: ingest, chunk, export.

Thin shells over traduko.documents; all parsing lives there so the
future editor API can reuse it. Artifacts: document.json (block tree),
chunks.json (translation batches), and translated.<ext> on export.
"""
from __future__ import annotations

from pathlib import Path

from ..budget import BudgetExceededError, BudgetMeter
from ..config import load_config
from ..documents.epubdoc import parse_epub, repack_epub
from ..documents.htmldoc import ParsedHtml, build_html_document
from ..documents.markdown import build_document, serialize_document
from ..documents.model import (
    Chunk,
    ChunksDoc,
    DocTranslationDoc,
    DocumentDoc,
    QcDoc,
)
from ..documents.qc import scan
from ..documents.translate import (
    DocTranslationSettings,
    translate_document_chunks,
)
from ..glossary import resolve_effective_glossary
from ..llm import LLMError
from ..prompts import PromptError, load_template
from ..translate import TranslationCanceled, TranslationError, TranslationPaused
from . import registry
from .base import (
    CancelRequested,
    PauseRequested,
    StageContext,
    StageError,
    StageResult,
)
from .common import resolve_llm, translate_template_for, translation_prompt_error

_EXTENSIONS = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
    ".html": "html",
    ".htm": "html",
    ".epub": "epub",
}

_OUTPUT_EXT = {"markdown": ".md", "txt": ".txt", "html": ".html", "epub": ".epub"}


def _detect_format(path: Path) -> str:
    fmt = _EXTENSIONS.get(path.suffix.lower())
    if fmt is None:
        supported = ", ".join(sorted(_EXTENSIONS))
        raise StageError(f"unsupported document type {path.suffix!r} ({supported})")
    return fmt


@registry.register
class IngestDocumentStage:
    type = "ingest_document"

    def run(self, ctx: StageContext) -> StageResult:
        path = Path(ctx.task.input_path)
        fmt = _detect_format(path)
        if fmt == "epub":
            doc = parse_epub(path)
        elif fmt == "html":
            doc = build_html_document(path.read_bytes())
        else:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise StageError(f"{path.name} is not valid UTF-8: {error}") from error
            doc = build_document(text, fmt)
        artifact = ctx.artifacts.write_json(
            ctx.stage_index + 1, "document.json", doc.model_dump(exclude={"schema_version"})
        )
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[artifact.name])


@registry.register
class ChunkStage:
    type = "chunk"

    def run(self, ctx: StageContext) -> StageResult:
        doc = DocumentDoc.model_validate(ctx.artifacts.read_latest_json("document.json"))
        base_blocks = int(ctx.params.get("base_blocks", 4))
        base_chars = int(ctx.params.get("base_chars", 2600))
        max_blocks = int(ctx.params.get("max_blocks", 80))
        max_chars = int(ctx.params.get("max_chars", 5200))

        chunks: list[Chunk] = []
        for chapter in doc.chapters:
            current: list[str] = []
            chars = 0

            def close() -> None:
                nonlocal current, chars
                if current:
                    chunks.append(
                        Chunk(
                            id=f"c-{len(chunks) + 1:04d}",
                            chapter_id=chapter.id,
                            block_ids=current,
                            char_count=chars,
                        )
                    )
                    current = []
                    chars = 0

            for block in chapter.blocks:
                if not block.translate:
                    continue
                size = len(block.text)
                if current and (
                    len(current) + 1 > max_blocks or chars + size > max_chars
                ):
                    close()
                current.append(block.id)
                chars += size
                if len(current) >= base_blocks or chars >= base_chars:
                    close()
            close()

        payload = ChunksDoc(chunks=chunks)
        artifact = ctx.artifacts.write_json(
            ctx.stage_index + 1, "chunks.json", payload.model_dump(exclude={"schema_version"})
        )
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[artifact.name])


@registry.register
class TranslateChunksStage:
    type = "translate_chunks"

    def run(self, ctx: StageContext) -> StageResult:
        doc = DocumentDoc.model_validate(ctx.artifacts.read_latest_json("document.json"))
        chunks = ChunksDoc.model_validate(ctx.artifacts.read_latest_json("chunks.json"))
        target_language = ctx.params.get("target_language")
        if not target_language:
            raise StageError("translate_chunks stage requires params.target_language")
        source_language = ctx.params.get("source_language", "auto")
        if source_language == "auto":
            source_language = "unknown"

        retry_ids: set[str] | None = None
        prior: DocTranslationDoc | None = None
        if ctx.params.get("only_flagged"):
            try:
                prior = DocTranslationDoc.model_validate(
                    ctx.artifacts.read_latest_json("translation.json")
                )
                qc = QcDoc.model_validate(ctx.artifacts.read_latest_json("qc.json"))
            except FileNotFoundError as error:
                raise StageError(
                    "only_flagged requires translation and qc artifacts"
                ) from error
            retry_ids = {flag.chunk_id for flag in qc.flags} | {
                chunk.id for chunk in prior.chunks if chunk.status != "translated"
            }
            if not retry_ids:
                ctx.emit_progress(1, 1)
                return StageResult()

        config = load_config(ctx.data_root)
        provider, model = resolve_llm(ctx.params, config)
        meter = BudgetMeter(ctx.data_root, ctx.bus, config)
        settings = DocTranslationSettings(
            source_language=source_language,
            target_language=target_language,
            model=model,
            style=ctx.params.get("style", ""),
            context_tail=int(ctx.params.get("context_tail", 5)),
            summary_chunks=int(ctx.params.get("summary_chunks", 10)),
            summary_chars=int(ctx.params.get("summary_chars", 16000)),
            temperature=ctx.params.get("temperature"),
        )
        partial_path = ctx.artifacts.path_for(
            ctx.stage_index + 1, "translation.partial.json"
        )
        summary_path = ctx.artifacts.path_for(ctx.stage_index + 1, "summary.json")
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        template, overridden = translate_template_for(ctx, "doc-translate")
        try:
            translation = translate_document_chunks(
                doc,
                chunks,
                settings,
                provider,
                meter,
                resolve_effective_glossary(ctx.data_root, ctx.task),
                template,
                load_template(ctx.data_root, "doc-summary"),
                project=ctx.task.project,
                task_id=ctx.task.id,
                partial_path=partial_path,
                summary_path=summary_path,
                emit_progress=ctx.emit_progress,
                should_pause=ctx.should_pause,
                should_cancel=ctx.should_cancel,
                retry_ids=retry_ids,
                prior=prior,
            )
        except BudgetExceededError as error:
            raise PauseRequested(str(error)) from error
        except TranslationCanceled as error:
            raise CancelRequested(str(error)) from error
        except TranslationPaused as error:
            raise PauseRequested(str(error)) from error
        except PromptError as error:
            raise translation_prompt_error(error, overridden) from error
        except (TranslationError, LLMError) as error:
            raise StageError(str(error)) from error

        path = ctx.artifacts.write_json(
            ctx.stage_index + 1,
            "translation.json",
            translation.model_dump(exclude={"schema_version"}),
        )
        artifacts = [path.name, partial_path.name]
        if summary_path.exists():
            artifacts.append(summary_path.name)
        # The retry round is the last chance to fix failed chunks before
        # export; letting it complete would let the task finish "green"
        # while the output silently keeps source text. State is written
        # first so the editor and a resume see the failed chunks.
        if ctx.params.get("only_flagged"):
            bad = sum(1 for c in translation.chunks if c.status != "translated")
            if bad:
                raise StageError(
                    f"{bad} of {len(translation.chunks)} chunks failed "
                    "translation; check the llm provider in settings or fix "
                    "them in the text editor, then run again"
                )
        return StageResult(artifacts=artifacts)


@registry.register
class QcScanStage:
    type = "qc_scan"

    def run(self, ctx: StageContext) -> StageResult:
        doc = DocumentDoc.model_validate(ctx.artifacts.read_latest_json("document.json"))
        chunks = ChunksDoc.model_validate(ctx.artifacts.read_latest_json("chunks.json"))
        try:
            translation = DocTranslationDoc.model_validate(
                ctx.artifacts.read_latest_json("translation.json")
            )
        except FileNotFoundError as error:
            raise StageError("qc_scan stage requires a translation artifact") from error
        qc = scan(
            doc,
            chunks,
            translation,
            resolve_effective_glossary(ctx.data_root, ctx.task),
            ctx.params.get("target_language", ""),
        )
        path = ctx.artifacts.write_json(
            ctx.stage_index + 1, "qc.json", qc.model_dump(exclude={"schema_version"})
        )
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[path.name])


def _translated_blocks(ctx: StageContext) -> dict[str, str]:
    """Block id -> translated text. A profile without a translate stage has
    no translation artifact and exports the source unchanged, but chunks
    that failed (or were never attempted) block the export: silently
    falling back to source text would mark an untranslated file done."""
    try:
        raw = ctx.artifacts.read_latest_json("translation.json")
    except FileNotFoundError:
        return {}
    translation = DocTranslationDoc.model_validate(raw)
    bad = sum(1 for chunk in translation.chunks if chunk.status != "translated")
    if bad:
        raise StageError(
            f"cannot export: {bad} of {len(translation.chunks)} chunks are not "
            "translated; re-run translation or fix them in the text editor"
        )
    return {
        block.id: block.text
        for chunk in translation.chunks
        for block in chunk.blocks
    }


@registry.register
class ExportDocumentStage:
    type = "export_document"

    def run(self, ctx: StageContext) -> StageResult:
        doc = DocumentDoc.model_validate(ctx.artifacts.read_latest_json("document.json"))
        translations = _translated_blocks(ctx)
        source = Path(ctx.task.input_path)
        output = ctx.artifacts.path_for(
            ctx.stage_index + 1, f"translated{_OUTPUT_EXT[doc.format]}"
        )
        output.parent.mkdir(parents=True, exist_ok=True)

        if doc.format == "epub":
            repack_epub(source, output, doc, translations)
        elif doc.format == "html":
            parsed = ParsedHtml(source.read_bytes())
            by_anchor = {
                block.anchor: translations[block.id]
                for chapter in doc.chapters
                for block in chapter.blocks
                if block.id in translations
            }
            parsed.apply(by_anchor)
            output.write_text(parsed.serialize(), encoding="utf-8")
        else:
            output.write_text(serialize_document(doc, translations), encoding="utf-8")
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[output.name])
