from pathlib import Path

import pytest

from traduko.agents.tools import ToolError
from traduko.config import SkillConfig
from traduko.skillhub import (
    SkillsManager,
    SkillValidationError,
    active_prompt_block,
    active_tools,
    set_active,
)


def write_skill(
    root: Path,
    directory: str,
    *,
    name: str | None = None,
    description: str = "A test skill.",
    body: str = "Follow these instructions.",
    extra_frontmatter: str = "",
) -> Path:
    """Write skills/<directory>/SKILL.md; frontmatter name defaults to the
    directory name."""
    skill_dir = root / "skills" / directory
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "---\n"
        f"name: {name if name is not None else directory}\n"
        f"description: {description}\n"
        f"{extra_frontmatter}"
        "---\n"
        f"{body}\n"
    )
    path = skill_dir / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


def on_config(name: str) -> dict[str, SkillConfig]:
    return {name: SkillConfig(enabled=True, confirmed=True)}


# --- parsing and validation via list_skills -------------------------------


def test_valid_skill_lists_with_config_defaults(tmp_path: Path) -> None:
    write_skill(tmp_path, "style-guide", description="Honorific rules.")
    rows = SkillsManager(tmp_path, {}).list_skills()
    # On disk but absent from config: listed, disabled and unconfirmed.
    assert rows == [
        {
            "name": "style-guide",
            "description": "Honorific rules.",
            "enabled": False,
            "confirmed": False,
            "valid": True,
            "errors": [],
        }
    ]


def test_extra_frontmatter_fields_are_not_validated(tmp_path: Path) -> None:
    write_skill(
        tmp_path, "tooled", extra_frontmatter="allowed-tools: [grep, read]\n"
    )
    rows = SkillsManager(tmp_path, {}).list_skills()
    assert rows[0]["valid"] is True
    assert rows[0]["errors"] == []


def test_boundary_lengths_are_valid(tmp_path: Path) -> None:
    name = "a" * 64
    write_skill(tmp_path, name, description="d" * 1024)
    rows = SkillsManager(tmp_path, {}).list_skills()
    assert rows[0]["valid"] is True


def test_frontmatter_name_must_match_directory(tmp_path: Path) -> None:
    write_skill(tmp_path, "style-guide", name="other-name")
    rows = SkillsManager(tmp_path, {}).list_skills()
    assert rows[0]["valid"] is False
    assert any("directory" in error for error in rows[0]["errors"])


@pytest.mark.parametrize(
    "bad_name",
    [
        "Upper-Case",
        "under_score",
        "-leading",
        "trailing-",
        "double--dash",
        "a" * 65,
    ],
)
def test_invalid_names_rejected(tmp_path: Path, bad_name: str) -> None:
    write_skill(tmp_path, bad_name)
    rows = SkillsManager(tmp_path, {}).list_skills()
    assert rows[0]["valid"] is False
    assert rows[0]["errors"]


def test_description_too_long(tmp_path: Path) -> None:
    write_skill(tmp_path, "wordy", description="d" * 1025)
    rows = SkillsManager(tmp_path, {}).list_skills()
    assert rows[0]["valid"] is False
    assert any("description" in error for error in rows[0]["errors"])


def test_empty_body_rejected(tmp_path: Path) -> None:
    write_skill(tmp_path, "hollow", body="   ")
    rows = SkillsManager(tmp_path, {}).list_skills()
    assert rows[0]["valid"] is False
    assert any("body" in error for error in rows[0]["errors"])


def test_missing_name_and_description_both_reported(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "sparse"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nother: x\n---\nBody.\n")
    rows = SkillsManager(tmp_path, {}).list_skills()
    assert rows[0]["valid"] is False
    assert any("name" in error for error in rows[0]["errors"])
    assert any("description" in error for error in rows[0]["errors"])


def test_file_without_frontmatter(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "bare"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Just text, no fences.\n")
    rows = SkillsManager(tmp_path, {}).list_skills()
    assert rows[0]["valid"] is False
    assert any("frontmatter" in error for error in rows[0]["errors"])


def test_unterminated_frontmatter(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "open-ended"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: open-ended\n")
    rows = SkillsManager(tmp_path, {}).list_skills()
    assert rows[0]["valid"] is False
    assert any("frontmatter" in error for error in rows[0]["errors"])


def test_all_failures_accumulate(tmp_path: Path) -> None:
    write_skill(tmp_path, "multi", name="Other_Name", description="d" * 1025, body="")
    rows = SkillsManager(tmp_path, {}).list_skills()
    assert rows[0]["valid"] is False
    assert len(rows[0]["errors"]) >= 3


def test_non_utf8_file_degrades_to_invalid(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "binary"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(b"---\nname: binary\n\xff\xfe---\n")
    rows = SkillsManager(tmp_path, {}).list_skills()
    assert rows[0]["valid"] is False
    assert any("unreadable" in error for error in rows[0]["errors"])


# --- list merge with config ----------------------------------------------


def test_config_entry_without_directory_reports_missing(tmp_path: Path) -> None:
    manager = SkillsManager(
        tmp_path, {"ghost": SkillConfig(enabled=True, confirmed=True)}
    )
    assert manager.list_skills() == [
        {
            "name": "ghost",
            "description": "",
            "enabled": True,
            "confirmed": True,
            "valid": False,
            "errors": ["missing"],
        }
    ]


def test_list_merges_disk_and_config_sorted(tmp_path: Path) -> None:
    write_skill(tmp_path, "beta")
    write_skill(tmp_path, "alpha")
    manager = SkillsManager(
        tmp_path,
        {
            "beta": SkillConfig(enabled=True, confirmed=True),
            "zeta": SkillConfig(enabled=True, confirmed=False),
        },
    )
    rows = manager.list_skills()
    assert [row["name"] for row in rows] == ["alpha", "beta", "zeta"]
    by_name = {row["name"]: row for row in rows}
    assert by_name["alpha"]["enabled"] is False
    assert by_name["beta"]["enabled"] is True
    assert by_name["beta"]["confirmed"] is True
    assert by_name["zeta"]["errors"] == ["missing"]
    assert by_name["zeta"]["confirmed"] is False


# --- prompt_block ---------------------------------------------------------


def qualifying_mix(tmp_path: Path) -> SkillsManager:
    write_skill(tmp_path, "good-one", description="Good description.")
    write_skill(tmp_path, "pending-one")
    write_skill(tmp_path, "dormant-one")
    write_skill(tmp_path, "broken-one", body="")
    return SkillsManager(
        tmp_path,
        {
            "good-one": SkillConfig(enabled=True, confirmed=True),
            "pending-one": SkillConfig(enabled=True, confirmed=False),
            "dormant-one": SkillConfig(enabled=False),
            "broken-one": SkillConfig(enabled=True, confirmed=True),
            "ghost-one": SkillConfig(enabled=True, confirmed=True),
        },
    )


def test_prompt_block_lists_only_qualifying_skills(tmp_path: Path) -> None:
    block = qualifying_mix(tmp_path).prompt_block()
    assert "good-one: Good description." in block
    assert "use_skill" in block
    for excluded in ("pending-one", "dormant-one", "broken-one", "ghost-one"):
        assert excluded not in block


def test_bom_prefixed_skill_is_valid(tmp_path: Path) -> None:
    # Windows editors prepend a BOM; utf-8-sig loading keeps the
    # frontmatter fence intact instead of reporting a misleading error.
    path = write_skill(tmp_path, "bom-one", description="Windows edited.")
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    manager = SkillsManager(tmp_path, on_config("bom-one"))
    assert manager.list_skills()[0]["valid"] is True
    assert manager.use_skill("bom-one") == "Follow these instructions."
    assert manager.read("bom-one").startswith("---")


def test_prompt_block_folds_description_whitespace(tmp_path: Path) -> None:
    # A multi-line description must not be able to forge extra list
    # entries or instruction lines in the prompt block.
    skill_dir = tmp_path / "skills" / "fold-one"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: fold-one\n"
        "description: |\n"
        "  First line.\n"
        "  - fake-skill: injected entry\n"
        "---\n"
        "Body.\n",
        encoding="utf-8",
    )
    block = SkillsManager(tmp_path, on_config("fold-one")).prompt_block()
    assert "fold-one: First line. - fake-skill: injected entry" in block
    assert len(block.split("\n")) == 2


def test_prompt_block_empty_when_no_qualifying_skill(tmp_path: Path) -> None:
    write_skill(tmp_path, "pending-one")
    manager = SkillsManager(
        tmp_path, {"pending-one": SkillConfig(enabled=True, confirmed=False)}
    )
    assert manager.prompt_block() == ""
    assert SkillsManager(tmp_path, {}).prompt_block() == ""


# --- agent_tools / use_skill ---------------------------------------------


def test_agent_tools_single_use_skill_returns_full_body(tmp_path: Path) -> None:
    body = "Step one.\n\nStep two, with detail."
    write_skill(tmp_path, "deep-skill", body=body)
    manager = SkillsManager(tmp_path, on_config("deep-skill"))
    tools = manager.agent_tools()
    assert [tool.name for tool in tools] == ["use_skill"]
    assert tools[0].parameters["name"]["type"] == "string"
    assert tools[0].parameters["name"]["required"] is True
    assert tools[0].handler({"name": "deep-skill"}) == body


def test_use_skill_rejects_non_qualifying_names(tmp_path: Path) -> None:
    manager = qualifying_mix(tmp_path)
    handler = manager.agent_tools()[0].handler
    for name in (
        "never-heard-of",
        "pending-one",
        "dormant-one",
        "broken-one",
        "ghost-one",
    ):
        with pytest.raises(ToolError):
            handler({"name": name})


def test_agent_tools_empty_without_qualifying_skill(tmp_path: Path) -> None:
    write_skill(tmp_path, "pending-one")
    manager = SkillsManager(
        tmp_path, {"pending-one": SkillConfig(enabled=True, confirmed=False)}
    )
    assert manager.agent_tools() == []
    assert SkillsManager(tmp_path, {}).agent_tools() == []


# --- read / write ---------------------------------------------------------


def test_read_returns_raw_file_content(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "readable")
    content = SkillsManager(tmp_path, {}).read("readable")
    assert content == path.read_text(encoding="utf-8")
    assert content.startswith("---\n")


def test_read_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        SkillsManager(tmp_path, {}).read("nope")


def test_write_valid_content_creates_file(tmp_path: Path) -> None:
    manager = SkillsManager(tmp_path, {})
    content = "---\nname: fresh-skill\ndescription: New.\n---\nDo the thing.\n"
    manager.write("fresh-skill", content)
    path = tmp_path / "skills" / "fresh-skill" / "SKILL.md"
    assert path.read_text(encoding="utf-8") == content
    assert manager.list_skills()[0]["valid"] is True


def test_write_invalid_content_raises_and_leaves_file(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "guarded")
    before = path.read_text(encoding="utf-8")
    manager = SkillsManager(tmp_path, {})
    with pytest.raises(ValueError) as excinfo:
        manager.write("guarded", "---\nname: guarded\ndescription: x\n---\n\n")
    assert isinstance(excinfo.value, SkillValidationError)
    assert any("body" in error for error in excinfo.value.errors)
    assert path.read_text(encoding="utf-8") == before


def test_write_rejects_frontmatter_name_mismatch(tmp_path: Path) -> None:
    manager = SkillsManager(tmp_path, {})
    with pytest.raises(SkillValidationError):
        manager.write(
            "one-name", "---\nname: other-name\ndescription: x\n---\nBody.\n"
        )
    assert not (tmp_path / "skills" / "one-name").exists()


# --- create / delete ------------------------------------------------------


def test_create_scaffolds_valid_skill(tmp_path: Path) -> None:
    manager = SkillsManager(tmp_path, {})
    manager.create("new-skill")
    rows = manager.list_skills()
    assert rows == [
        {
            "name": "new-skill",
            "description": rows[0]["description"],
            "enabled": False,
            "confirmed": False,
            "valid": True,
            "errors": [],
        }
    ]
    assert rows[0]["description"]


def test_create_existing_raises(tmp_path: Path) -> None:
    manager = SkillsManager(tmp_path, {})
    manager.create("dupe")
    with pytest.raises(FileExistsError):
        manager.create("dupe")


def test_create_invalid_name_raises(tmp_path: Path) -> None:
    manager = SkillsManager(tmp_path, {})
    with pytest.raises(SkillValidationError):
        manager.create("Bad_Name")
    assert not (tmp_path / "skills" / "Bad_Name").exists()


def test_delete_removes_skill_directory(tmp_path: Path) -> None:
    write_skill(tmp_path, "doomed")
    manager = SkillsManager(tmp_path, {})
    manager.delete("doomed")
    assert not (tmp_path / "skills" / "doomed").exists()


def test_delete_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        SkillsManager(tmp_path, {}).delete("nope")


# --- module-level active registry ----------------------------------------


def test_active_defaults_to_neutral_values() -> None:
    set_active(None)
    assert active_prompt_block() == ""
    assert active_tools() == []


def test_active_forwards_to_manager(tmp_path: Path) -> None:
    write_skill(tmp_path, "live-skill", description="Live.")
    manager = SkillsManager(tmp_path, on_config("live-skill"))
    set_active(manager)
    try:
        assert "live-skill" in active_prompt_block()
        assert [tool.name for tool in active_tools()] == ["use_skill"]
    finally:
        set_active(None)
