"""Seed a fresh data root with default profiles, prompts, pricing, styles.

Idempotent: writes files that do not exist yet, and replaces a seeded file
still byte-identical to an older version this project shipped. User edits are
never overwritten. Seeded files are plain text with comments; they are
documentation the user can read in place.
"""
from __future__ import annotations

import hashlib
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


# Every version of a seeded file this project has shipped, by sha256 of its
# content.
#
# Seeding writes only files that do not exist yet, which protects user edits
# but also means a data root never receives a fixed pipeline. A root created
# before v2-02 kept a novel-translate profile with no translate_chunks stage,
# so every document task since produced no translation.json: the text editor
# and the translation settings stayed unreachable on a pipeline that looked
# complete. A file whose content still matches one of these hashes is one the
# user never touched, so replacing it with the current version loses nothing
# and costs an upgrade they cannot otherwise get.
#
# Existing tasks keep the stage list they were created with; this only
# changes what the next task built from the profile looks like.
#
# When you change a seeded file, add its previous hash here.
# test_seeds.py::test_every_shipped_seed_version_is_recorded reads them out of
# the git history and fails with the missing hash if you forget.
_SHIPPED_VERSIONS: dict[str, frozenset[str]] = {
    "profiles/av-default.yaml": frozenset(
        {
            "01782a57036a1de74d99cefd09104731a12546a79da525e32ca992acb85f09e7",
            "04a6a9880bc26d82452b4181158e6a7e10e56e18cba35b56778c8cde08128a30",
            "e8f372d21e63f6181e3f9c90c0b110c98a8b3d90caf0bdd389f5448f8e211915",
        }
    ),
    "profiles/subtitle-translate.yaml": frozenset(
        {
            "31e4c907e8556e99a62c71563e68f4ae77f1c622a5c76bc44e62567918870a98",
            "ed512b61a83ede6006a9302f10e5a7a567eba7917b83bcf8bc717063cc91e2c9",
        }
    ),
    "profiles/novel-translate.yaml": frozenset(
        {
            "5738635de6120aeac23bd7e8ec7b2b4e2d23de2170ffd400f431b5ed46a8514f",
            "e81ddb8bf32bb315b571defd86fb144ed821a017a83402943d0ac4726a60c438",
            "ef71df7b9e0bf19c99c01c0c5ca9e186dab0144ee7ee14c510c1de1fdec395cd",
        }
    ),
    "profiles/av-dub.yaml": frozenset(
        {
            "68d5e8b7c26aace1d699045e14ae41593e3718038d99224dc612dc38a1796698",
            "c97190fb13e7dd8e8419ac7308ff5147884d3370461218c9e4db00b49296b323",
        }
    ),
    "profiles/translate-pdf.yaml": frozenset(
        {"a2828d1a6f963bfab416fcacc0e59a83ff3af40a04106e08abbbc79c6f846ced"}
    ),
    "profiles/audio-transcribe.yaml": frozenset(
        {"f8fcacd8a9a483b7a6c2bcef7c4d1ec39afb28e96e60f16ac02f07d5451df45b"}
    ),
    "profiles/audio-translate.yaml": frozenset(
        {"b2e5cdb71f8967d32d5177b7503fb5558e39bf8f833d79c74a72eeaafd953ca5"}
    ),
    "profiles/audio-dub.yaml": frozenset(
        {"f80430d6928b40f70e35ecd5bc0cb5efcc53e49fb23dfb9fdb1f1ab7fab6e143"}
    ),
    "profiles/video-compose.yaml": frozenset(
        {"ed75d4f3ed7811f59fd234a11e90319ff9180695aa657a70e3945931c1cdc5be"}
    ),
    "profiles/audio-compose.yaml": frozenset(
        {"56aa8aac0196fbb20dec2fe78794b00e6c36663a9e616ea27c28e054dd8d0977"}
    ),
    "config/styles.yaml": frozenset(
        {"d80455243ce2010e077335a8118fdfdced41b939545b4640e210cdf590dbc88e"}
    ),
}


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_untouched_older_version(path: Path, rel: str, current: str) -> bool:
    """True when the file on disk is a version this project shipped and is no
    longer the current one. Anything else -- a user edit, a hand-written
    profile -- is left alone."""
    shipped = _SHIPPED_VERSIONS.get(rel)
    if shipped is None:
        return False
    try:
        on_disk = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if on_disk == current:
        return False
    return content_hash(on_disk) in shipped


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
        if path.exists() and not _is_untouched_older_version(path, rel, content):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
