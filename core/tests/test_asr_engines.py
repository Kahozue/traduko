"""Engine-id level tests: resolution order and provider mapping."""
from traduko.config import AsrConfig, CoreConfig
from traduko.asr.engines import (
    ENGINES,
    engine_provider,
    engine_timestamps,
    resolve_engine,
)


def make_config(**asr_kwargs) -> CoreConfig:
    return CoreConfig(asr=AsrConfig(**asr_kwargs))


def test_engine_catalog_marks_timestamp_capability() -> None:
    ids = {e.id for e in ENGINES}
    assert {
        "faster_whisper",
        "macos_native",
        "openai_whisper",
        "openai_gpt4o_diarize",
        "openai_gpt4o",
        "openai_gpt4o_mini",
        "cloud_custom",
    } <= ids
    assert engine_timestamps("openai_whisper") is True
    assert engine_timestamps("openai_gpt4o") is False
    assert engine_timestamps("openai_gpt4o_mini") is False
    assert engine_timestamps("openai_gpt4o_diarize") is True


def test_resolve_engine_explicit_auto_and_default() -> None:
    config = make_config(engine="openai_whisper", audio_engine="openai_gpt4o")
    assert resolve_engine({"engine": "macos_native"}, config) == "macos_native"
    assert resolve_engine({"engine": "auto"}, config) == "openai_whisper"
    assert resolve_engine({"engine": "auto_audio"}, config) == "openai_gpt4o"
    assert resolve_engine({}, config) == "openai_whisper"
    # audio default follows the video default when unset.
    config2 = make_config(engine="faster_whisper", audio_engine="")
    assert resolve_engine({"engine": "auto_audio"}, config2) == "faster_whisper"


def test_resolve_engine_legacy_provider_params_win() -> None:
    config = make_config(engine="openai_whisper")
    # Old profiles pin provider names directly; they bypass the engine layer.
    assert resolve_engine({"provider": "faster_whisper"}, config) is None


def test_engine_provider_mapping_faster_whisper_uses_config_model() -> None:
    config = make_config(model="medium")
    name, options, timestamps = engine_provider("faster_whisper", config)
    assert name == "faster_whisper"
    assert options == {"model_size": "medium"}
    assert timestamps is True


def test_engine_provider_mapping_openai_cloud_entries() -> None:
    config = make_config(cloud_api_key="sk-1", cloud_base_url="https://api.openai.com/v1")
    name, options, timestamps = engine_provider("openai_whisper", config)
    assert name == "openai_cloud"
    assert options["model"] == "whisper-1"
    assert options["mode"] == "verbose"
    assert options["api_key"] == "sk-1"
    assert timestamps is True

    name, options, timestamps = engine_provider("openai_gpt4o", config)
    assert options["model"] == "gpt-4o-transcribe"
    assert options["mode"] == "text"
    assert timestamps is False

    name, options, _ = engine_provider("openai_gpt4o_diarize", config)
    assert options["model"] == "gpt-4o-transcribe-diarize"
    assert options["mode"] == "diarize"


def test_engine_provider_mapping_custom_endpoint() -> None:
    config = make_config(
        custom_base_url="https://groq.example/v1",
        custom_api_key_env="GROQ_KEY",
        custom_model="whisper-large-v3",
    )
    name, options, timestamps = engine_provider("cloud_custom", config)
    assert name == "openai_cloud"
    assert options["base_url"] == "https://groq.example/v1"
    assert options["api_key_env"] == "GROQ_KEY"
    assert options["model"] == "whisper-large-v3"
    assert options["mode"] == "auto"
    assert timestamps is True


def test_engine_provider_macos_uses_locale() -> None:
    config = make_config(macos_locale="ja-JP")
    name, options, timestamps = engine_provider("macos_native", config)
    assert name == "macos_native"
    assert options == {"locale": "ja-JP"}
    assert timestamps is True


def test_zh_prompt_forwarded_to_cloud_options() -> None:
    config = make_config(zh_prompt=False)
    _, options, _ = engine_provider("openai_whisper", config)
    assert options["zh_prompt"] is False
