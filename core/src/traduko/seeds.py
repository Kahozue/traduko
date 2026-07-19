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
    DEFAULT_GLOSSARY_PROOFREAD_TEMPLATE,
    DEFAULT_PROOFREAD_TEMPLATE,
    DEFAULT_TRANSLATE_TEMPLATE,
)

_PROFILE_AV_DEFAULT = """\
# Default audiovisual pipeline: video or audio file in, subtitle file out.
# Set target_language before real use. "fake" provider means: use the
# default provider configured in settings (config default_provider, or the
# sole llm_providers entry); with none configured it is an offline dry run.
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
# Set target_language before real use. "fake" provider means: use the
# default provider configured in settings (config default_provider, or the
# sole llm_providers entry); with none configured it is an offline dry run.
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
# Set target_language before real use. "fake" provider means: use the
# default provider configured in settings (config default_provider, or the
# sole llm_providers entry); with none configured it is an offline dry run.
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

_PROFILE_TRANSLATE_PDF = """\
# PDF pipeline: PDF in, translated PDF (mono + bilingual) out. Needs the
# PDF engine installed from the settings document tab. The engine
# (pdf2zh-next, BabelDOC backend) makes its own LLM calls; point provider
# at an entry under llm_providers in config/core.yaml and it forwards the
# endpoint and key. "fake" leaves the engine to its own default.
schema_version: 1
name: translate-pdf
stages:
  - type: translate_pdf
    params:
      provider: fake
      source_lang: auto
      target_lang: en
"""

_PROFILE_AUDIO_TRANSCRIBE = """\
# Audio transcript pipeline: audio file in, plain transcript out.
# engine: auto_audio uses the audio-domain default from the settings audio
# tab; timestampless engines (gpt-4o-transcribe) are fine here because no
# subtitle timing is needed.
schema_version: 1
name: audio-transcribe
kind: audio
stages:
  - type: extract_audio
  - type: asr
    params:
      engine: auto_audio
  - type: export_transcript
"""

_PROFILE_AUDIO_TRANSLATE = """\
# Audio translation pipeline: audio in, translated transcript + srt out.
# The segment stage needs timestamps, so pick a timestamped engine
# (whisper-1, faster-whisper or macOS native) as the audio default; the
# preflight blocks timestampless engines here with a clear message.
# Set target_language before real use.
schema_version: 1
name: audio-translate
kind: audio
stages:
  - type: extract_audio
  - type: asr
    params:
      engine: auto_audio
  - type: segment
  - type: translate
    params:
      provider: fake
      target_language: en
  - type: proofread
    params:
      provider: fake
      intensity: fast
  - type: export_transcript
  - type: export_subtitles
    params:
      formats: [srt]
"""

_PROFILE_AUDIO_DUB = """\
# Audio dubbing pipeline: audio in, dubbed audio file out. Needs a
# timestamped ASR engine plus the dubbing engine and Hugging Face token
# from the settings video tab. Pauses after diarize for speaker review.
# Set target_language before real use.
schema_version: 1
name: audio-dub
kind: audio
stages:
  - type: extract_audio
  - type: asr
    params:
      engine: auto_audio
  - type: segment
  - type: translate
    params:
      provider: fake
      target_language: en
  - type: proofread
    params:
      provider: fake
      intensity: fast
  - type: diarize
    pause_after: true
  - type: tts_synthesize
  - type: align_duration
  - type: mix_audio
  - type: export_audio
"""

_PROFILE_VIDEO_COMPOSE = """\
# Compose a dubbed video: video file in, transcript in (as a stage param,
# not as the task input), dubbed video out. No ASR and no translation --
# the transcript is the dub text, so dub_text is pinned to original.
# The transcript source is set when the task is created; a plain-text
# transcript with no timestamps makes align_duration lay the clips end to
# end instead of fitting them to the original timing.
# Needs the dubbing engine from the settings video tab, plus a Hugging Face
# token there when cloning the original speakers.
schema_version: 1
name: video-compose
kind: video
stages:
  - type: ingest_transcript
  - type: diarize
    params:
      dub_text: original
    pause_after: true
  - type: tts_synthesize
    params:
      dub_text: original
  - type: align_duration
    params:
      dub_text: original
  - type: mix_audio
  - type: mux
"""

_PROFILE_AUDIO_COMPOSE = """\
# Compose an audio file from a transcript: transcript in, dubbed audio out.
# Pure synthesis, so there is no source recording to clone a voice from or
# to mix under the dub: voice_mode is design and the dub is laid over
# silence. Supply reference audio per speaker in the dubbing studio to clone
# a voice anyway. Needs the dubbing engine from the settings video tab.
schema_version: 1
name: audio-compose
kind: audio
stages:
  - type: ingest_transcript
  - type: diarize
    params:
      dub_text: original
      voice_mode: design
    pause_after: true
  - type: tts_synthesize
    params:
      dub_text: original
      voice_mode: design
  - type: align_duration
    params:
      dub_text: original
      voice_mode: design
  - type: mix_audio
  - type: export_audio
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
        "profiles/translate-pdf.yaml": _PROFILE_TRANSLATE_PDF,
        "profiles/audio-transcribe.yaml": _PROFILE_AUDIO_TRANSCRIBE,
        "profiles/audio-translate.yaml": _PROFILE_AUDIO_TRANSLATE,
        "profiles/audio-dub.yaml": _PROFILE_AUDIO_DUB,
        "profiles/video-compose.yaml": _PROFILE_VIDEO_COMPOSE,
        "profiles/audio-compose.yaml": _PROFILE_AUDIO_COMPOSE,
        "prompts/translate.txt": DEFAULT_TRANSLATE_TEMPLATE,
        "prompts/proofread.txt": DEFAULT_PROOFREAD_TEMPLATE,
        "prompts/glossary_proofread.txt": DEFAULT_GLOSSARY_PROOFREAD_TEMPLATE,
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
