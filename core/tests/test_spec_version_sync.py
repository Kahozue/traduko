"""CI assertion 1: spec-version sync between design-language and the checklist.

``internal/`` is gitignored (dev-only docs), so this runs on a developer
machine where both files exist and skips where they do not (e.g. a CI
checkout). That is intended: the job is to stop a developer bumping
design-language.md without re-checking the acceptance checklist. The Stop
hook and commit-time ``pnpm test`` / ``pytest`` are where it bites; on CI it
is a no-op rather than a false red.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DESIGN_LANGUAGE = ROOT / "internal" / "design-language.md"
CHECKLIST = ROOT / "internal" / "ui-acceptance-checklist.md"


def test_checklist_tracks_design_language_version() -> None:
    if not DESIGN_LANGUAGE.exists() or not CHECKLIST.exists():
        pytest.skip("internal/ docs absent (gitignored; e.g. CI checkout)")

    dl_match = re.search(r"版本\s*([0-9]+\.[0-9]+)", DESIGN_LANGUAGE.read_text(encoding="utf-8"))
    cl_match = re.search(
        r"design-language\.md:\s*v([0-9]+\.[0-9]+)", CHECKLIST.read_text(encoding="utf-8")
    )
    assert dl_match, "could not find '版本 X.Y' in design-language.md"
    assert cl_match, "could not find aligned 'design-language.md: vX.Y' in the checklist"
    assert dl_match.group(1) == cl_match.group(1), (
        f"design-language.md is v{dl_match.group(1)} but the checklist's aligned "
        f"block says v{cl_match.group(1)}. Re-check the checklist against the new "
        "design-language version, then update its aligned block."
    )
