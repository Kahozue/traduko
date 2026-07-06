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

DEFAULT_TEMPLATES: dict[str, str] = {"translate": DEFAULT_TRANSLATE_TEMPLATE}


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
