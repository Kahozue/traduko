from pathlib import Path

import pytest

from traduko.artifacts import ArtifactStore
from traduko.events import EventBus
from traduko.models import StageRecord, TaskRecord, utc_now_iso
from traduko.stages import base, pdf, registry


def make_ctx(
    tmp_path: Path,
    input_path: Path,
    stage_index: int = 0,
    params: dict | None = None,
):
    now = utc_now_iso()
    task = TaskRecord(
        id="t-pdf",
        project="default",
        input_path=str(input_path),
        profile="translate-pdf",
        stages=[StageRecord(type="noop")],
        created_at=now,
        updated_at=now,
    )
    task_dir = tmp_path / "projects" / "default" / "tasks" / task.id
    progress: list[tuple[int, int]] = []
    ctx = base.StageContext(
        task=task,
        stage_index=stage_index,
        params=params or {},
        artifacts=ArtifactStore(task_dir),
        data_root=tmp_path,
        emit_progress=lambda cur, total: progress.append((cur, total)),
        should_cancel=lambda: False,
        bus=EventBus(),
    )
    ctx.artifacts.dir.mkdir(parents=True, exist_ok=True)
    return ctx, progress


def install_engine(tmp_path: Path) -> None:
    target = tmp_path / "engines" / "pdf"
    (target / "venv" / "bin").mkdir(parents=True, exist_ok=True)
    (target / "venv" / "bin" / "python").write_text("", encoding="utf-8")
    (target / ".installed").write_text("{}", encoding="utf-8")


def test_translate_pdf_registered() -> None:
    assert isinstance(registry.create("translate_pdf"), pdf.TranslatePdfStage)


def test_rejects_non_pdf_input(tmp_path: Path) -> None:
    ctx, _ = make_ctx(tmp_path, tmp_path / "book.epub", params={"target_lang": "zh"})
    with pytest.raises(base.StageError, match="pdf"):
        pdf.TranslatePdfStage().run(ctx)


def test_requires_installed_engine(tmp_path: Path) -> None:
    book = tmp_path / "book.pdf"
    book.write_bytes(b"%PDF-1.4")
    ctx, _ = make_ctx(tmp_path, book, params={"target_lang": "zh"})
    with pytest.raises(base.StageError, match="not installed"):
        pdf.TranslatePdfStage().run(ctx)


def test_requires_target_lang(tmp_path: Path) -> None:
    book = tmp_path / "book.pdf"
    book.write_bytes(b"%PDF-1.4")
    install_engine(tmp_path)
    ctx, _ = make_ctx(tmp_path, book, params={})
    with pytest.raises(base.StageError, match="target_lang"):
        pdf.TranslatePdfStage().run(ctx)


def test_happy_path_registers_output_pdfs(tmp_path: Path, monkeypatch) -> None:
    book = tmp_path / "book.pdf"
    book.write_bytes(b"%PDF-1.4")
    install_engine(tmp_path)
    captured = {}

    def fake_run(cmd, emit_progress):
        captured["cmd"] = cmd
        emit_progress(50, 100)
        out_dir = Path(cmd[cmd.index("--output") + 1])
        (out_dir / "book.mono.pdf").write_bytes(b"%PDF-mono")
        (out_dir / "book.dual.pdf").write_bytes(b"%PDF-dual")

    monkeypatch.setattr(pdf, "_run_pdf", fake_run)
    ctx, progress = make_ctx(
        tmp_path, book, params={"target_lang": "zh", "source_lang": "en"}
    )
    result = pdf.TranslatePdfStage().run(ctx)
    assert sorted(result.artifacts) == ["01-book.dual.pdf", "01-book.mono.pdf"]
    assert (ctx.artifacts.dir / "01-book.mono.pdf").exists()
    assert "--lang-out" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--lang-out") + 1] == "zh"
    assert (50, 100) in progress


def test_forwards_provider_endpoint(tmp_path: Path, monkeypatch) -> None:
    from traduko.config import CoreConfig, save_config

    book = tmp_path / "book.pdf"
    book.write_bytes(b"%PDF-1.4")
    install_engine(tmp_path)
    config = CoreConfig()
    config.llm_providers["main"] = {
        "type": "openai_compat",
        "base_url": "https://api.example.test/v1",
        "api_key": "sk-test",
        "model": "gpt-4o-mini",
    }
    save_config(tmp_path, config)

    def fake_run(cmd, emit_progress):
        out_dir = Path(cmd[cmd.index("--output") + 1])
        (out_dir / "book.mono.pdf").write_bytes(b"%PDF")

    monkeypatch.setattr(pdf, "_run_pdf", fake_run)
    ctx, _ = make_ctx(
        tmp_path, book, params={"target_lang": "zh", "provider": "main"}
    )
    result = pdf.TranslatePdfStage().run(ctx)
    assert result.artifacts == ["01-book.mono.pdf"]


def test_no_output_raises(tmp_path: Path, monkeypatch) -> None:
    book = tmp_path / "book.pdf"
    book.write_bytes(b"%PDF-1.4")
    install_engine(tmp_path)
    monkeypatch.setattr(pdf, "_run_pdf", lambda cmd, emit_progress: None)
    ctx, _ = make_ctx(tmp_path, book, params={"target_lang": "zh"})
    with pytest.raises(base.StageError, match="no output"):
        pdf.TranslatePdfStage().run(ctx)
