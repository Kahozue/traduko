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

    model/base_url/api_key forward the chosen provider's endpoint to the
    engine, which makes its own LLM calls. Empty values are omitted.
    """
    cmd = [
        str(venv_python),
        "-m",
        "pdf2zh_next",
        str(input_path),
        "--output",
        str(out_dir),
        "--lang-in",
        source_lang,
        "--lang-out",
        target_lang,
    ]
    if model:
        cmd += ["--model", model]
    if base_url:
        cmd += ["--base-url", base_url]
    if api_key:
        cmd += ["--api-key", api_key]
    return cmd
