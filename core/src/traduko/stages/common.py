"""Helpers shared by LLM-driven stages, plus the transcript fallback the
export and dub stages both read through."""
from __future__ import annotations

from ..config import CoreConfig, resolve_provider_name
from ..llm import LLMError, LLMProvider, create_llm
from ..prompts import PromptError, load_template
from .base import StageContext, StageError


def normalize_segments_doc(data: dict) -> dict:
    """Common shape for translation/segments/asr docs: the text of an
    untranslated doc lands in source, a translation adds target."""
    segments = []
    for seg in data["segments"]:
        norm = {
            "id": seg["id"],
            "start": seg.get("start", 0.0),
            "end": seg.get("end", 0.0),
            "source": seg.get("source", seg.get("text", "")),
        }
        if "target" in seg:
            norm["target"] = seg["target"]
        if "speaker" in seg:
            norm["speaker"] = seg["speaker"]
        segments.append(norm)
    return {
        "language": data.get("language") or data.get("source_language"),
        "target_language": data.get("target_language"),
        "segments": segments,
    }


def read_transcript_chain(ctx: StageContext, names: list[str]) -> dict | None:
    """First readable artifact in `names`, normalized. None when the task has
    produced none of them yet."""
    for name in names:
        try:
            return normalize_segments_doc(ctx.artifacts.read_latest_json(name))
        except FileNotFoundError:
            continue
    return None


def resolve_llm(params: dict, config: CoreConfig) -> tuple[LLMProvider, str]:
    provider_name = resolve_provider_name(config, params.get("provider"))
    provider_config = config.llm_providers.get(provider_name)
    if provider_config is None:
        if provider_name == "fake":
            provider_config = {"type": "fake"}
        else:
            raise StageError(
                f"unknown llm provider: {provider_name} "
                "(define it under llm_providers in config/core.yaml)"
            )
    provider_config = dict(provider_config)
    default_model = provider_config.pop("model", None)
    model = params.get("model") or default_model or "fake-model"
    try:
        provider = create_llm(provider_config)
    except LLMError as error:
        raise StageError(str(error)) from error
    return provider, model


def translate_template_for(ctx, template_name: str) -> tuple[str, bool]:
    """The prompt a translate stage should render, plus whether it came from
    the task's own params. A task-level override replaces the template file
    entirely but takes the same variables, so render still validates it."""
    override = (ctx.params.get("prompt_override") or "").strip()
    if override:
        return override, True
    return load_template(ctx.data_root, template_name), False


def translation_prompt_error(error: PromptError, overridden: bool) -> StageError:
    """PromptError means the prompt asked for a variable the stage does not
    supply. Name the task-level prompt override when that is what is wrong,
    so the user knows which of the two places to go fix."""
    if overridden:
        return StageError(
            f"this task's prompt override could not be rendered: {error}"
        )
    return StageError(f"prompt template could not be rendered: {error}")
