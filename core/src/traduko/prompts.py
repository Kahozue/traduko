"""Prompt templates: builtin defaults, fully overridable per data root."""
from __future__ import annotations

from pathlib import Path
from string import Template


class PromptError(Exception):
    pass


DEFAULT_TRANSLATE_TEMPLATE = """You are a professional subtitle translator. Translate each segment from ${source_language} to ${target_language}.

Rules:
- Keep each translation concise and natural for subtitles.
- Follow the glossary exactly when a term appears.
- Return ONLY a JSON array, one object per input segment, in the same order: [{"id": 1, "text": "translated"}]
- Keep the same ids. Do not merge, split, or drop segments.

Style notes: ${style}

Glossary (source -> target):
${glossary}

Previous context:
${context}

SEGMENTS:
${segments_json}
"""

DEFAULT_PROOFREAD_TEMPLATE = """You are a professional subtitle proofreader. Review the translation from ${source_language} to ${target_language} and fix real problems: mistranslations, awkward phrasing, glossary violations, inconsistent terminology. Do not rewrite acceptable lines.

There are ${total_segments} segments, ids 1..${total_segments}.

Work in rounds:
1. Scan all segments with read_segments in windows of about 20 ids, and run check_glossary once per round.
2. Fix each problem you find: edit_segment for a single line (always give a reason), retranslate_range for a badly translated span, flag_segment when a human should decide.
3. After one full pass, close the round with end_round.
4. Finish with {"done": true, "summary": "..."} only when a full pass finds no new issues.

Glossary (source -> target):
${glossary}
"""

DEFAULT_GLOSSARY_PROOFREAD_TEMPLATE = """You are a transcription proofreader. The segments below are speech-recognition text with terms from a glossary.

Rules:
- Correct only proper-name spelling errors that can be resolved from the glossary, including phonetic recognition mistakes.
- Do not rewrite for fluency and do not translate.
- Return ONLY a JSON array with one object for every input id: [{"id": 1, "text": "corrected"}]
- Keep every id. Return unchanged text when no correction is needed.

Source language: ${source_language}

Glossary (source -> target):
${glossary}

SEGMENTS:
${segments_json}
"""

DEFAULT_DOC_TRANSLATE_TEMPLATE = """You are a professional literary translator. Translate each block from ${source_language} to ${target_language}.

Rules:
- Follow the glossary exactly when a term appears.
- Preserve the block role: headings stay headings, keep inline markup as-is.
- Return ONLY a JSON array, one object per input block, in the same order: [{"id": "b-00001", "text": "translated"}]
- Keep the same ids. Do not merge, split, or drop blocks.

Glossary (source -> target):
${glossary}

Story so far:
${summary}

Previous context:
${context}

BLOCKS:
${blocks_json}
"""

DEFAULT_DOC_SUMMARY_TEMPLATE = """You maintain a running summary of a book being translated into ${target_language}. Update it with the new text below: keep characters, places, terminology, and open plot threads; drop details that no longer matter. Answer in ${target_language} with the updated summary only, at most 300 words.

Current summary:
${summary}

New translated text:
${recent_text}
"""

DEFAULT_TEMPLATES: dict[str, str] = {
    "translate": DEFAULT_TRANSLATE_TEMPLATE,
    "proofread": DEFAULT_PROOFREAD_TEMPLATE,
    "glossary_proofread": DEFAULT_GLOSSARY_PROOFREAD_TEMPLATE,
    "doc-translate": DEFAULT_DOC_TRANSLATE_TEMPLATE,
    "doc-summary": DEFAULT_DOC_SUMMARY_TEMPLATE,
}


def load_template(root: Path, name: str) -> str:
    override = root / "prompts" / f"{name}.txt"
    if override.exists():
        return override.read_text(encoding="utf-8")
    if name in DEFAULT_TEMPLATES:
        return DEFAULT_TEMPLATES[name]
    raise PromptError(f"unknown prompt template: {name}")


def render(template: str, variables: dict[str, str]) -> str:
    try:
        return Template(template).substitute(variables)
    except (KeyError, ValueError) as error:
        raise PromptError(f"prompt render failed: {error}") from error
