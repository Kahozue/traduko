"""CI assertion 2 (core half): label-map completeness across core->app.

Guards the recurring R3 M1 defect: a new core stage/event/status ships
without an app i18n label. This half asserts the checked-in
``labels_contract.json`` still reflects core's authoritative enums. The app
half (``app/src/lib/labels.contract.test.ts``) asserts the app renders every
entry in that contract. When core adds an enum member this test goes red
until the JSON is updated, which in turn makes the app test demand the
matching label. Two gates in series close the boundary.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from traduko.events import EVENT_TYPES
from traduko.models import StageStatus, TaskStatus
from traduko.profiles import list_profiles_detailed
from traduko.seeds import ensure_defaults

CONTRACT = Path(__file__).resolve().parents[1] / "src" / "traduko" / "labels_contract.json"


def _authoritative() -> dict[str, list[str]]:
    """Core's real enums, derived by running the seed logic, not by parsing."""
    root = Path(tempfile.mkdtemp())
    ensure_defaults(root)
    profiles = list_profiles_detailed(root)
    stage_types = sorted({s for p in profiles for s in p["stages"]})
    # assistant_* events are the live assistant stream; events.py marks them
    # skipped by the task event logger, so the event list never renders them.
    event_types = sorted(e for e in EVENT_TYPES if not e.startswith("assistant_"))
    return {
        "stage_types": stage_types,
        "event_types_ui": event_types,
        "task_statuses": sorted(s.value for s in TaskStatus),
        "stage_statuses": sorted(s.value for s in StageStatus),
    }


def test_labels_contract_matches_core_enums() -> None:
    expected = _authoritative()
    stored = json.loads(CONTRACT.read_text(encoding="utf-8"))
    actual = {k: v for k, v in stored.items() if not k.startswith("_")}
    assert actual == expected, (
        "core enums drifted from labels_contract.json. Set the JSON to the "
        "value below, then add matching app labels + i18n (the app-side test "
        "will tell you which are missing):\n"
        + json.dumps(expected, ensure_ascii=False, indent=2)
    )
