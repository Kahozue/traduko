"""PDF translation stage: drives pdf2zh-next in its engine venv.

The engine is invoked over subprocess (never imported) so its AGPL-3.0
licence stays behind the process boundary. It writes a mono (target-only)
and a dual (bilingual) PDF, which we register as artifacts.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..config import CoreConfig, load_config, resolve_provider_name
from ..pdfengine.runner import build_translate_cmd
from ..pdfengine.setup import PdfManager, venv_python
from . import registry
from .base import StageContext, StageError, StageResult

_PROGRESS_RE_PREFIXES = ("%", "progress")


def _make_manager(data_root: Path, config: CoreConfig) -> PdfManager:
    return PdfManager(data_root, python_override=config.pdf.python)


def _run_pdf(cmd: list[str], emit_progress) -> None:
    """Run the engine CLI, forwarding percentage progress it prints.

    Non-zero exit raises StageError with the tail of stderr.
    """
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    assert process.stdout is not None
    for line in process.stdout:
        for token in line.replace("%", " % ").split():
            if token.endswith("%"):
                token = token[:-1]
            try:
                pct = int(float(token))
            except ValueError:
                continue
            if 0 <= pct <= 100:
                emit_progress(pct, 100)
    code = process.wait()
    if code != 0:
        raise StageError(f"pdf2zh-next exited with code {code}")


@registry.register
class TranslatePdfStage:
    type = "translate_pdf"

    def run(self, ctx: StageContext) -> StageResult:
        input_path = Path(ctx.task.input_path)
        if input_path.suffix.lower() != ".pdf":
            raise StageError(f"translate_pdf needs a .pdf input, got {input_path.suffix!r}")

        config = load_config(ctx.data_root)
        manager = _make_manager(ctx.data_root, config)
        if not manager.status()["installed"]:
            raise StageError(
                "PDF engine is not installed; install it from the settings document tab"
            )

        target_lang = ctx.params.get("target_lang")
        if not target_lang:
            raise StageError("translate_pdf stage requires params.target_lang")
        source_lang = ctx.params.get("source_lang") or "auto"

        base_url = api_key = model = ""
        provider_name = resolve_provider_name(config, ctx.params.get("provider"))
        if provider_name != "fake":
            entry = config.llm_providers.get(provider_name)
            if entry is None:
                raise StageError(
                    f"unknown llm provider: {provider_name} "
                    "(define it under llm_providers in config/core.yaml)"
                )
            base_url = entry.get("base_url", "")
            api_key = entry.get("api_key", "")
            model = ctx.params.get("model") or entry.get("model", "")

        out_dir = ctx.artifacts.dir / f"{ctx.stage_index + 1:02d}-pdf"
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = build_translate_cmd(
            venv_python(ctx.data_root),
            input_path,
            out_dir,
            source_lang,
            target_lang,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
        _run_pdf(cmd, ctx.emit_progress)

        produced = sorted(p for p in out_dir.glob("*.pdf") if p.is_file())
        if not produced:
            raise StageError("pdf2zh-next produced no output PDF")
        artifacts: list[str] = []
        for pdf in produced:
            dest = ctx.artifacts.path_for(ctx.stage_index + 1, pdf.name)
            pdf.replace(dest)
            artifacts.append(dest.name)
        out_dir.rmdir()
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=artifacts)
