"""File-based proposal store: the write channel of the safety gate.

Agents may only PROPOSE config changes; a human approves or rejects them.
Each proposal lives as one JSON file at ``data_root/proposals/<id>.json``
(the plan's "ProposalStore", realized as module-level functions taking the
data root, mirroring ``config.load_config``/``save_config``).

Lifecycle: ``propose_config`` validates the merged result FIRST and raises
``pydantic.ValidationError`` on an invalid patch without writing anything;
callers (service 422 handlers, agent tool handlers) render ``str(exc)`` as
the readable failure message. ``approve`` re-reads the config at approve
time, deep-merges the stored patch against the CURRENT values, re-validates,
then saves — so unrelated config changes made between propose and approve
survive. Unknown ids raise ``KeyError``; resolving a non-pending proposal
raises ``ValueError``.
"""
from __future__ import annotations

import difflib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .config import CONFIG_FILE, CoreConfig, load_config, save_config
from .fsutil import atomic_write_text

PROPOSALS_DIR = "proposals"

# `confirmed` on skills/mcp_servers entries is the v2-05 safety gate: it is
# granted only through the settings panel's confirmation card (where the user
# reviews the SKILL.md full text / MCP tool list), never through the proposal
# channel. The settings page writes config via PUT /config, not via proposals,
# so no legitimate flow ever hits this guard.
CONFIRMATION_GATED_SECTIONS = ("skills", "mcp_servers")
CONFIRMED_VIA_PROPOSAL_ERROR = (
    "confirmed cannot be set through the proposal channel: confirmation is "
    "granted only from the settings panel after the user reviews the skill "
    "or server; propose enabled only"
)


def patch_grants_confirmation(patch: dict) -> bool:
    """True if any ``skills``/``mcp_servers`` entry in ``patch`` carries a
    truthy ``confirmed`` — the one field the proposal channel must never set."""
    for section in CONFIRMATION_GATED_SECTIONS:
        entries = patch.get(section)
        if not isinstance(entries, dict):
            continue
        for entry in entries.values():
            if isinstance(entry, dict) and entry.get("confirmed"):
                return True
    return False


def _deep_merge(base: dict, patch: dict) -> dict:
    """Recursively merge ``patch`` into ``base`` (dicts merge, leaves replace)."""
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _render_yaml(config: CoreConfig) -> str:
    # Must match save_config's dump call exactly so diffs mirror the on-disk file.
    return yaml.safe_dump(config.model_dump(), sort_keys=True, allow_unicode=True)


def _unified_diff(old: CoreConfig, new: CoreConfig) -> str:
    return "".join(
        difflib.unified_diff(
            _render_yaml(old).splitlines(keepends=True),
            _render_yaml(new).splitlines(keepends=True),
            fromfile=f"{CONFIG_FILE} (current)",
            tofile=f"{CONFIG_FILE} (proposed)",
        )
    )


def _merge_and_validate(current: CoreConfig, patch: dict) -> CoreConfig:
    # pydantic's model_copy(update=...) is shallow; merge raw dicts instead.
    return CoreConfig.model_validate(_deep_merge(current.model_dump(), patch))


def _proposal_path(root: Path, proposal_id: str) -> Path:
    return root / PROPOSALS_DIR / f"{proposal_id}.json"


def _new_id(root: Path) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    while True:
        proposal_id = f"prop-{timestamp}-{secrets.token_hex(2)}"
        if not _proposal_path(root, proposal_id).exists():
            return proposal_id


def _write(root: Path, proposal: dict) -> None:
    atomic_write_text(
        _proposal_path(root, proposal["id"]),
        json.dumps(proposal, ensure_ascii=False, indent=2),
    )


def _load(root: Path, proposal_id: str) -> dict:
    path = _proposal_path(root, proposal_id)
    if not path.exists():
        raise KeyError(proposal_id)
    return json.loads(path.read_text(encoding="utf-8"))


def _load_pending(root: Path, proposal_id: str) -> dict:
    proposal = _load(root, proposal_id)
    if proposal["status"] != "pending":
        raise ValueError(
            f"proposal {proposal_id} is {proposal['status']!r}, not pending"
        )
    return proposal


def propose_config(root: Path, patch: dict, reason: str) -> dict:
    """Validate ``patch`` against the current config and store a pending proposal.

    Raises ``pydantic.ValidationError`` (and writes nothing) if the merged
    config is invalid. ``confirmed`` cannot be set through the proposal
    channel: a patch granting it on any skills/mcp_servers entry raises
    ``ValueError`` (and writes nothing), because confirmation is only ever
    granted from the settings panel. Returns the stored proposal dict.
    """
    if patch_grants_confirmation(patch):
        raise ValueError(CONFIRMED_VIA_PROPOSAL_ERROR)
    current = load_config(root)
    new_config = _merge_and_validate(current, patch)
    proposal = {
        "id": _new_id(root),
        "kind": "config",
        "reason": reason,
        "patch": patch,
        "diff": _unified_diff(current, new_config),
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write(root, proposal)
    return proposal


def candidate_config(root: Path, proposal_id: str) -> CoreConfig:
    """The config a pending proposal would produce, without applying it.

    Callers pre-flight side effects (notifier construction in the service)
    against the returned config before committing via ``approve``. Same
    taxonomy as ``approve``: ``KeyError`` unknown id, ``ValueError``
    non-pending, ``pydantic.ValidationError`` invalid merge. Writes nothing.
    """
    proposal = _load_pending(root, proposal_id)
    return _merge_and_validate(load_config(root), proposal["patch"])


def approve(root: Path, proposal_id: str) -> dict:
    """Apply a pending proposal against the CURRENT config and mark it applied.

    The config is re-read and the stored patch re-merged and re-validated at
    approve time, so changes made since propose survive. On any validation
    error nothing is saved and the proposal stays pending.
    """
    proposal = _load_pending(root, proposal_id)
    current = load_config(root)
    new_config = _merge_and_validate(current, proposal["patch"])
    save_config(root, new_config)
    proposal["status"] = "applied"
    _write(root, proposal)
    return proposal


def reject(root: Path, proposal_id: str) -> dict:
    """Mark a pending proposal rejected without touching the config."""
    proposal = _load_pending(root, proposal_id)
    proposal["status"] = "rejected"
    _write(root, proposal)
    return proposal


def list_proposals(root: Path, status: str | None = None) -> list[dict]:
    """All proposals sorted by id (chronological), optionally filtered by status."""
    directory = root / PROPOSALS_DIR
    if not directory.exists():
        return []
    proposals = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]
    if status is not None:
        proposals = [p for p in proposals if p["status"] == status]
    return proposals
