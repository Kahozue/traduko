"""Seed a fresh data root with default profiles, prompts, pricing, styles.

Idempotent: only writes files that do not exist yet, so user edits are
never overwritten. Seeded files are plain text with comments; they are
documentation the user can read in place.
"""
from __future__ import annotations

from pathlib import Path

from .budget import BUILTIN_PRICES
from .prompts import (
    DEFAULT_DOC_SUMMARY_TEMPLATE,
    DEFAULT_DOC_TRANSLATE_TEMPLATE,
    DEFAULT_PROOFREAD_TEMPLATE,
    DEFAULT_TRANSLATE_TEMPLATE,
)

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

_PROFILE_NOVEL_TRANSLATE = """\
# Novel/document pipeline: markdown, txt, epub, or html in, same format
# out. The second translate_chunks pass re-translates only the chunks the
# first qc_scan flagged (plus failed ones); chunks still flagged in the
# final qc.json are left for proofreading and the editor.
# Before real use: set target_language, and point provider at an entry
# under llm_providers in config/core.yaml ("fake" is an offline dry run).
schema_version: 1
name: novel-translate
stages:
  - type: ingest_document
  - type: chunk
    params:
      base_blocks: 4
      base_chars: 2600
      max_blocks: 80
      max_chars: 5200
  - type: translate_chunks
    params:
      provider: fake
      target_language: en
  - type: qc_scan
    params:
      target_language: en
  - type: translate_chunks
    params:
      provider: fake
      target_language: en
      only_flagged: true
  - type: qc_scan
    params:
      target_language: en
  - type: export_document
"""

_PROFILE_AV_DUB = """\
# Dubbing pipeline: video in, dubbed video out. Needs the dubbing engine
# installed from the settings video tab, plus a Hugging Face token there
# for the diarization model. The pipeline pauses after diarize so you
# can review speaker assignments before synthesis.
# Before real use: set target_language, and point provider at an entry
# under llm_providers in config/core.yaml ("fake" is an offline dry run).
schema_version: 1
name: av-dub
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
  - type: diarize
    pause_after: true
  - type: tts_synthesize
  - type: align_duration
  - type: mix_audio
  - type: mux
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
        "profiles/novel-translate.yaml": _PROFILE_NOVEL_TRANSLATE,
        "profiles/av-dub.yaml": _PROFILE_AV_DUB,
        "prompts/translate.txt": DEFAULT_TRANSLATE_TEMPLATE,
        "prompts/proofread.txt": DEFAULT_PROOFREAD_TEMPLATE,
        "prompts/doc-translate.txt": DEFAULT_DOC_TRANSLATE_TEMPLATE,
        "prompts/doc-summary.txt": DEFAULT_DOC_SUMMARY_TEMPLATE,
        "config/pricing.yaml": _pricing_yaml(),
        "config/styles.yaml": _STYLES_DEFAULT,
    }
    for rel, content in seeds.items():
        path = root / rel
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
