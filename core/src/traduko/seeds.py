"""Seed a fresh data root with default profiles, prompts, pricing, styles.

Idempotent: only writes files that do not exist yet, so user edits are
never overwritten. Seeded files are plain text with comments; they are
documentation the user can read in place.
"""
from __future__ import annotations

from pathlib import Path

from .budget import BUILTIN_PRICES
from .prompts import DEFAULT_PROOFREAD_TEMPLATE, DEFAULT_TRANSLATE_TEMPLATE

_PROFILE_AV_DEFAULT = """\
# Default audiovisual pipeline: video or audio file in, subtitle file out.
# Before real use: set target_language, and point provider at an entry
# under llm_providers in config/core.yaml ("fake" is an offline dry run).
schema_version: 1
name: av-default
stages:
  - type: extract_audio
  - type: asr
    params:
      provider: faster_whisper
  - type: segment
  - type: translate
    params:
      provider: fake
      target_language: en
  - type: proofread
    params:
      provider: fake
      intensity: fast
  - type: export_subtitles
    params:
      formats: [srt]
"""

_PROFILE_SUBTITLE_TRANSLATE = """\
# Subtitle-file pipeline: srt/vtt/ass/txt in, translated subtitles out.
schema_version: 1
name: subtitle-translate
stages:
  - type: ingest_subtitle
  - type: translate
    params:
      provider: fake
      target_language: en
  - type: proofread
    params:
      provider: fake
      intensity: fast
  - type: export_subtitles
    params:
      formats: [srt]
"""

_STYLES_DEFAULT = """\
# Named subtitle style presets (ASS-based), referenced by style_preset.
default:
  font_name: Arial
  font_size: 48
  primary_color: "#FFFFFF"
  outline_color: "#000000"
  outline: 2.0
  shadow: 0.0
  bold: false
  alignment: 2
  margin_v: 40
"""


def _pricing_yaml() -> str:
    lines = ["# USD per 1M tokens. Edit freely; unknown models are billed as 0."]
    for model, (input_price, output_price) in sorted(BUILTIN_PRICES.items()):
        lines.append(f"{model}:")
        lines.append(f"  input: {input_price}")
        lines.append(f"  output: {output_price}")
    return "\n".join(lines) + "\n"


def ensure_defaults(root: Path) -> None:
    seeds = {
        "profiles/av-default.yaml": _PROFILE_AV_DEFAULT,
        "profiles/subtitle-translate.yaml": _PROFILE_SUBTITLE_TRANSLATE,
        "prompts/translate.txt": DEFAULT_TRANSLATE_TEMPLATE,
        "prompts/proofread.txt": DEFAULT_PROOFREAD_TEMPLATE,
        "config/pricing.yaml": _pricing_yaml(),
        "config/styles.yaml": _STYLES_DEFAULT,
    }
    for rel, content in seeds.items():
        path = root / rel
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
