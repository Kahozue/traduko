"""PDF engine subprocess command building (no imports of pdf2zh)."""
from __future__ import annotations

from pathlib import Path


def build_translate_cmd(
    venv_python: str | Path,
    input_path: str | Path,
    out_dir: str | Path,
    source_lang: str,
    target_lang: str,
    model: str = "",
    base_url: str = "",
    api_key: str = "",
) -> list[str]:
    """Assemble the pdf2zh-next CLI invocation.

    The package ships no runnable __main__, so the entry point is the venv
    console script that lives next to the interpreter. A provider with a
    base_url is forwarded through the engine's OpenAI-compatible backend
    (the engine makes its own LLM calls); without one the engine falls back
    to its built-in default service.
    """
    cli = Path(venv_python).parent / "pdf2zh_next"
    cmd = [
        str(cli),
        str(input_path),
        "--output",
        str(out_dir),
        "--lang-in",
        source_lang,
        "--lang-out",
        target_lang,
    ]
    if base_url:
        cmd.append("--openaicompatible")
        cmd += ["--openai-compatible-base-url", base_url]
        if model:
            cmd += ["--openai-compatible-model", model]
        if api_key:
            cmd += ["--openai-compatible-api-key", api_key]
    return cmd
