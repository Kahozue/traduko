from pathlib import Path

from traduko.pdfengine.runner import build_translate_cmd


def test_basic_cmd() -> None:
    cmd = build_translate_cmd(
        "/venv/bin/python",
        Path("/in/book.pdf"),
        Path("/out"),
        "auto",
        "zh",
    )
    assert cmd == [
        "/venv/bin/python",
        "-m",
        "pdf2zh_next",
        "/in/book.pdf",
        "--output",
        "/out",
        "--lang-in",
        "auto",
        "--lang-out",
        "zh",
    ]


def test_provider_flags_forwarded() -> None:
    cmd = build_translate_cmd(
        "/venv/bin/python",
        "/in/book.pdf",
        "/out",
        "en",
        "zh",
        model="gpt-4o-mini",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
    )
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "gpt-4o-mini"
    assert cmd[cmd.index("--base-url") + 1] == "https://api.example.test/v1"
    assert cmd[cmd.index("--api-key") + 1] == "sk-test"


def test_empty_provider_flags_omitted() -> None:
    cmd = build_translate_cmd("/py", "/in.pdf", "/out", "auto", "zh", model="")
    assert "--model" not in cmd
    assert "--base-url" not in cmd
    assert "--api-key" not in cmd
