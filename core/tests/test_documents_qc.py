from traduko.documents.model import (
    Block,
    Chapter,
    Chunk,
    ChunksDoc,
    DocumentDoc,
    DocTranslationDoc,
    TranslatedChunk,
)
from traduko.documents.qc import (
    glossary_violations,
    is_echo,
    is_untranslated,
    normalize,
    scan,
    similarity,
)
from traduko.glossary import GlossaryEntry


def test_normalize_collapses_whitespace_and_case() -> None:
    assert normalize("  Hello\n\tWorld  ") == "hello world"


def test_untranslated_exact_and_near_match() -> None:
    sentence = "The quick brown fox jumps over the lazy dog."
    assert is_untranslated(sentence, sentence, "zh-TW")
    assert is_untranslated(sentence, sentence[:-1] + "!", "en")
    assert not is_untranslated(sentence, "敏捷的棕色狐狸跳過懶狗。", "zh-TW")


def test_untranslated_similarity_threshold() -> None:
    source = "a" * 100
    barely_same = "a" * 97 + "xyz"
    assert similarity(source, barely_same) >= 0.96
    assert is_untranslated(source, barely_same, "en")
    clearly_different = "a" * 50 + "b" * 50
    assert not is_untranslated(source, clearly_different, "en")


def test_untranslated_kanji_exemption_for_chinese_target() -> None:
    kanji_only = "東京大学図書館"
    assert not is_untranslated(kanji_only, kanji_only, "zh-TW")
    # Same text is still flagged when the target language is not Chinese.
    assert is_untranslated(kanji_only, kanji_only, "en")
    # Two or more hiragana defeat the exemption.
    with_hiragana = "東京の大学はここ"
    assert is_untranslated(with_hiragana, with_hiragana, "zh-TW")
    # Latin source into Chinese has no exemption.
    assert is_untranslated("hello world", "hello world", "zh-TW")


def test_untranslated_empty_strings_never_flag() -> None:
    assert not is_untranslated("", "", "en")
    assert not is_untranslated("text", "", "en")


def test_echo_threshold() -> None:
    source = "Line one.\nLine two.\nLine three.\n" * 5
    assert is_echo(source, source)
    assert not is_echo(source, "Completely different translated text.")


def test_glossary_violations_report_missing_targets() -> None:
    entries = [
        GlossaryEntry(source="Traduko", target="翻譯機"),
        GlossaryEntry(source="pipeline", target="管線"),
    ]
    hits = glossary_violations(
        "Traduko has a pipeline.", "Traduko 有一條管線。", entries
    )
    assert [e.source for e in hits] == ["Traduko"]


def _doc() -> tuple[DocumentDoc, ChunksDoc]:
    document = DocumentDoc(
        format="txt",
        chapters=[
            Chapter(
                id="ch-0001",
                blocks=[
                    Block(id="b-1", kind="paragraph", translate=True, text="First paragraph."),
                    Block(id="b-2", kind="paragraph", translate=True, text="Second paragraph."),
                    Block(id="b-3", kind="paragraph", translate=True, text="Third paragraph."),
                ],
            )
        ],
    )
    chunks = ChunksDoc(
        chunks=[
            Chunk(id="c-0001", chapter_id="ch-0001", block_ids=["b-1", "b-2"]),
            Chunk(id="c-0002", chapter_id="ch-0001", block_ids=["b-3"]),
        ]
    )
    return document, chunks


def test_scan_flags_untranslated_and_skips_failed_chunks() -> None:
    document, chunks = _doc()
    translation = DocTranslationDoc(
        chunks=[
            TranslatedChunk(
                id="c-0001",
                status="translated",
                blocks=[
                    {"id": "b-1", "text": "First paragraph."},
                    {"id": "b-2", "text": "第二段。"},
                ],
            ),
            TranslatedChunk(id="c-0002", status="failed", blocks=[]),
        ]
    )
    qc = scan(document, chunks, translation, [], "zh-TW")
    assert [(f.chunk_id, f.block_id, f.type) for f in qc.flags] == [
        ("c-0001", "b-1", "untranslated")
    ]


def test_scan_echo_flag_is_chunk_level_and_suppresses_block_flags() -> None:
    document, chunks = _doc()
    translation = DocTranslationDoc(
        chunks=[
            TranslatedChunk(
                id="c-0001",
                status="translated",
                blocks=[
                    {"id": "b-1", "text": "First paragraph."},
                    {"id": "b-2", "text": "Second paragraph."},
                ],
            ),
            TranslatedChunk(
                id="c-0002",
                status="translated",
                blocks=[{"id": "b-3", "text": "第三段。"}],
            ),
        ]
    )
    qc = scan(document, chunks, translation, [], "zh-TW")
    assert [(f.chunk_id, f.block_id, f.type) for f in qc.flags] == [
        ("c-0001", "", "echo")
    ]


def test_scan_glossary_violation() -> None:
    document, chunks = _doc()
    translation = DocTranslationDoc(
        chunks=[
            TranslatedChunk(
                id="c-0001",
                status="translated",
                blocks=[
                    {"id": "b-1", "text": "第一段。"},
                    {"id": "b-2", "text": "第二段。"},
                ],
            ),
            TranslatedChunk(
                id="c-0002",
                status="translated",
                blocks=[{"id": "b-3", "text": "第三段。"}],
            ),
        ]
    )
    glossary = [GlossaryEntry(source="First", target="首")]
    qc = scan(document, chunks, translation, glossary, "zh-TW")
    assert [(f.chunk_id, f.block_id, f.type) for f in qc.flags] == [
        ("c-0001", "b-1", "glossary")
    ]
    assert "First -> 首" in qc.flags[0].evidence
