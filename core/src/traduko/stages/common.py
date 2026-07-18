"""Helpers shared by LLM-driven stages."""
from __future__ import annotations

from ..config import CoreConfig, resolve_provider_name
from ..llm import LLMError, LLMProvider, create_llm
from .base import StageError


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
