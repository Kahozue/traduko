import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from traduko.config import load_config, save_config
from traduko.proposals import (
    approve,
    candidate_config,
    list_proposals,
    propose_config,
    reject,
)


def test_propose_writes_pending_file_with_diff(tmp_path: Path) -> None:
    proposal = propose_config(tmp_path, {"default_project": "novel-x"}, "switch project")

    assert re.fullmatch(r"prop-\d{14}-[0-9a-f]{4}", proposal["id"])
    assert proposal["kind"] == "config"
    assert proposal["reason"] == "switch project"
    assert proposal["patch"] == {"default_project": "novel-x"}
    assert proposal["status"] == "pending"
    created_at = datetime.fromisoformat(proposal["created_at"])
    assert created_at.utcoffset() == timedelta(0)

    assert "-default_project: default" in proposal["diff"]
    assert "+default_project: novel-x" in proposal["diff"]

    path = tmp_path / "proposals" / f"{proposal['id']}.json"
    assert path.exists()
    assert list_proposals(tmp_path) == [proposal]

    # Proposing must not touch the live config.
    assert load_config(tmp_path).default_project == "default"


def test_propose_deep_merges_nested_patch(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    config.budget.task_usd_limit = 5.0
    save_config(tmp_path, config)

    proposal = propose_config(tmp_path, {"budget": {"monthly_usd_limit": 20.0}}, "cap spend")

    assert "+  monthly_usd_limit: 20.0" in proposal["diff"]
    # Deep merge keeps the sibling key; a shallow merge would drop it.
    assert "-  task_usd_limit: 5.0" not in proposal["diff"]


def test_approve_applies_and_load_config_reflects(tmp_path: Path) -> None:
    proposal = propose_config(tmp_path, {"default_project": "novel-x"}, "switch")

    approved = approve(tmp_path, proposal["id"])

    assert approved["status"] == "applied"
    assert load_config(tmp_path).default_project == "novel-x"
    assert list_proposals(tmp_path, status="applied")[0]["id"] == proposal["id"]


def test_reject_keeps_config_and_marks_rejected(tmp_path: Path) -> None:
    proposal = propose_config(tmp_path, {"default_project": "novel-x"}, "switch")

    rejected = reject(tmp_path, proposal["id"])

    assert rejected["status"] == "rejected"
    assert load_config(tmp_path).default_project == "default"
    assert list_proposals(tmp_path, status="rejected")[0]["id"] == proposal["id"]


def test_invalid_patch_raises_and_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        propose_config(tmp_path, {"sync": {"mode": "ftp"}}, "bad transport")

    assert list_proposals(tmp_path) == []
    proposals_dir = tmp_path / "proposals"
    assert not proposals_dir.exists() or not any(proposals_dir.iterdir())


def test_approve_merges_against_current_config(tmp_path: Path) -> None:
    # Phase 1: propose patch A.
    proposal = propose_config(tmp_path, {"budget": {"task_usd_limit": 9.0}}, "raise cap")

    # Phase 2: the config gains unrelated change B after the proposal exists.
    config = load_config(tmp_path)
    config.budget.monthly_usd_limit = 100.0
    config.default_project = "other"
    save_config(tmp_path, config)

    approve(tmp_path, proposal["id"])

    final = load_config(tmp_path)
    assert final.budget.task_usd_limit == 9.0  # A applied
    assert final.budget.monthly_usd_limit == 100.0  # sibling B survives the deep merge
    assert final.default_project == "other"  # top-level B survives


def test_approve_stays_pending_on_unloadable_config(tmp_path: Path) -> None:
    proposal = propose_config(tmp_path, {"budget": {"task_usd_limit": 9.0}}, "raise cap")

    # The config drifts into an invalid state between propose and approve.
    config_path = tmp_path / "config" / "core.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("sync:\n  mode: ftp\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        approve(tmp_path, proposal["id"])

    # Nothing applied, proposal untouched.
    assert config_path.read_text(encoding="utf-8") == "sync:\n  mode: ftp\n"
    assert list_proposals(tmp_path, status="pending")[0]["id"] == proposal["id"]


def test_unknown_id_raises_key_error(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        approve(tmp_path, "prop-19700101000000-dead")
    with pytest.raises(KeyError):
        reject(tmp_path, "prop-19700101000000-dead")


def test_non_pending_proposal_cannot_be_resolved_again(tmp_path: Path) -> None:
    applied = propose_config(tmp_path, {"default_project": "a"}, "first")
    approve(tmp_path, applied["id"])
    with pytest.raises(ValueError):
        approve(tmp_path, applied["id"])
    with pytest.raises(ValueError):
        reject(tmp_path, applied["id"])

    rejected = propose_config(tmp_path, {"default_project": "b"}, "second")
    reject(tmp_path, rejected["id"])
    with pytest.raises(ValueError):
        approve(tmp_path, rejected["id"])
    with pytest.raises(ValueError):
        reject(tmp_path, rejected["id"])


def test_candidate_config_previews_without_applying(tmp_path: Path) -> None:
    proposal = propose_config(tmp_path, {"budget": {"task_usd_limit": 9.0}}, "raise cap")

    candidate = candidate_config(tmp_path, proposal["id"])

    assert candidate.budget.task_usd_limit == 9.0
    # Preview only: disk config and proposal status are untouched.
    assert load_config(tmp_path).budget.task_usd_limit is None
    assert list_proposals(tmp_path, status="pending")[0]["id"] == proposal["id"]

    with pytest.raises(KeyError):
        candidate_config(tmp_path, "prop-19700101000000-dead")

    approve(tmp_path, proposal["id"])
    with pytest.raises(ValueError):
        candidate_config(tmp_path, proposal["id"])


def test_list_proposals_sorted_and_filtered(tmp_path: Path) -> None:
    assert list_proposals(tmp_path) == []

    first = propose_config(tmp_path, {"default_project": "a"}, "one")
    second = propose_config(tmp_path, {"default_project": "b"}, "two")
    third = propose_config(tmp_path, {"default_project": "c"}, "three")
    reject(tmp_path, second["id"])
    approve(tmp_path, third["id"])

    listed = list_proposals(tmp_path)
    assert [p["id"] for p in listed] == sorted(p["id"] for p in (first, second, third))

    assert [p["id"] for p in list_proposals(tmp_path, status="pending")] == [first["id"]]
    assert [p["id"] for p in list_proposals(tmp_path, status="rejected")] == [second["id"]]
    assert [p["id"] for p in list_proposals(tmp_path, status="applied")] == [third["id"]]
