from pathlib import Path

from traduko.pdfengine.runner import build_translate_cmd


def test_basic_cmd_uses_console_script() -> None:
    cmd = build_translate_cmd(
        "/venv/bin/python",
        Path("/in/book.pdf"),
        Path("/out"),
        "auto",
        "zh",
    )
    assert cmd == [
        "/venv/bin/pdf2zh_next",
        "/in/book.pdf",
        "--output",
        "/out",
        "--lang-in",
        "auto",
        "--lang-out",
        "zh",
    ]


def test_provider_forwarded_through_openai_compatible_backend() -> None:
    cmd = build_translate_cmd(
        "/venv/bin/python",
        "/in/book.pdf",
        "/out",
        "en",
        "zh",
        model="gpt-5.4-mini",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
    )
    assert "--openaicompatible" in cmd
    assert (
        cmd[cmd.index("--openai-compatible-base-url") + 1]
        == "https://api.example.test/v1"
    )
    assert cmd[cmd.index("--openai-compatible-model") + 1] == "gpt-5.4-mini"
    assert cmd[cmd.index("--openai-compatible-api-key") + 1] == "sk-test"


def test_without_base_url_engine_default_backend_is_used() -> None:
    # A provider without a base_url (native adapters, fake) cannot be
    # forwarded as an OpenAI-compatible endpoint, so no backend flags at all.
    cmd = build_translate_cmd(
        "/py", "/in.pdf", "/out", "auto", "zh", model="m", api_key="k"
    )
    assert "--openaicompatible" not in cmd
    assert "--openai-compatible-model" not in cmd
    assert "--openai-compatible-api-key" not in cmd
