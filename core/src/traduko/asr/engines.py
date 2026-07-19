"""Engine-id layer: the settings menu speaks engine ids, the registry
speaks provider classes. This module maps between them.

An "engine" is a user-facing choice (faster-whisper, macOS native,
whisper-1, ...). A "provider" is a registered AsrProvider class; several
engines share the openai_cloud provider with different options.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import AsrConfig, CoreConfig


@dataclass(frozen=True)
class EngineInfo:
    id: str
    kind: str  # local | cloud
    timestamps: bool
    glossary_bias: bool


ENGINES: tuple[EngineInfo, ...] = (
    EngineInfo("faster_whisper", "local", True, True),
    EngineInfo("macos_native", "local", True, True),
    EngineInfo("openai_whisper", "cloud", True, True),
    EngineInfo("openai_gpt4o_diarize", "cloud", True, True),
    EngineInfo("openai_gpt4o", "cloud", False, True),
    EngineInfo("openai_gpt4o_mini", "cloud", False, True),
    EngineInfo("cloud_custom", "cloud", True, False),
)

_BY_ID = {engine.id: engine for engine in ENGINES}


def engine_timestamps(engine_id: str) -> bool:
    engine = _BY_ID.get(engine_id)
    return engine.timestamps if engine else True


def engine_glossary_bias(engine_id: str) -> bool:
    engine = _BY_ID.get(engine_id)
    return engine.glossary_bias if engine else False


def stage_glossary_bias(params: dict, config: CoreConfig) -> bool:
    """Whether an ASR stage can consume glossary terms.

    Legacy profiles name the registry provider directly instead of an engine
    id. The two local providers are unambiguous; a direct openai_cloud entry
    is treated conservatively because it may point at a custom endpoint.
    """
    engine_id = resolve_engine(params, config)
    if engine_id is not None:
        return engine_glossary_bias(engine_id)
    return params.get("provider") in {"faster_whisper", "macos_native"}


def resolve_engine(params: dict, config: CoreConfig) -> str | None:
    """Effective engine id for an asr stage, or None for the legacy path.

    Order: explicit params.engine ("auto" follows the video default,
    "auto_audio" the audio default), then legacy params.provider (None:
    the caller instantiates that registry provider directly), then the
    configured video default."""
    engine = str(params.get("engine") or "")
    if engine == "auto":
        return config.asr.engine
    if engine == "auto_audio":
        return config.asr.audio_engine or config.asr.engine
    if engine:
        return engine
    if params.get("provider"):
        return None
    return config.asr.engine


def _cloud_options(asr: AsrConfig, model: str, mode: str) -> dict:
    return {
        "base_url": asr.cloud_base_url,
        "api_key": asr.cloud_api_key,
        "api_key_env": asr.cloud_api_key_env,
        "model": model,
        "mode": mode,
        "zh_prompt": asr.zh_prompt,
    }


def engine_provider(engine_id: str, config: CoreConfig) -> tuple[str, dict, bool]:
    """(registry provider name, constructor options, has timestamps)."""
    asr = config.asr
    if engine_id == "faster_whisper":
        return "faster_whisper", {"model_size": asr.model}, True
    if engine_id == "macos_native":
        return "macos_native", {"locale": asr.macos_locale}, True
    if engine_id == "openai_whisper":
        return "openai_cloud", _cloud_options(asr, "whisper-1", "verbose"), True
    if engine_id == "openai_gpt4o_diarize":
        return (
            "openai_cloud",
            _cloud_options(asr, "gpt-4o-transcribe-diarize", "diarize"),
            True,
        )
    if engine_id == "openai_gpt4o":
        return "openai_cloud", _cloud_options(asr, "gpt-4o-transcribe", "text"), False
    if engine_id == "openai_gpt4o_mini":
        return (
            "openai_cloud",
            _cloud_options(asr, "gpt-4o-mini-transcribe", "text"),
            False,
        )
    if engine_id == "cloud_custom":
        options = {
            "base_url": asr.custom_base_url,
            "api_key": asr.custom_api_key,
            "api_key_env": asr.custom_api_key_env,
            "model": asr.custom_model,
            "mode": "auto",
            "zh_prompt": asr.zh_prompt,
        }
        return "openai_cloud", options, True
    raise ValueError(f"unknown asr engine: {engine_id}")
