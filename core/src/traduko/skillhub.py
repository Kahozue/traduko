"""Agent Skills: SKILL.md packages following the agentskills.io standard.

A skill is a directory under data/skills/<name>/ holding a SKILL.md with
yaml frontmatter and a markdown body. Loading is progressive, in three
layers: prompt_block() injects only name + description of every enabled,
confirmed and valid skill into the agent goal; the single use_skill tool
returns a skill's full body on demand; any other files in the directory
are kept but never parsed here.

Frontmatter is parsed by hand (a pair of --- fences + yaml.safe_load of
the block between). Validation follows agentskills.io: name and
description are required, the name is lowercase-hyphen, at most 64
characters and equal to the directory name, the description is at most
1024 characters, and the body must be non-empty. Every other frontmatter
field (allowed-tools included) is preserved verbatim and never acts as a
security boundary; the safety gate is the config pair enabled +
confirmed, and unconfirmed skills stay out of the prompt and out of
use_skill even when enabled.

The manager reads straight from disk on every call, so it needs no
supervisor or reload hook. The service registers one through
set_active(); stage code asks active_prompt_block()/active_tools() and
gets neutral values under the CLI where no manager runs.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from .agents.tools import AgentTool, ToolError
from .config import SkillConfig

SKILL_FILE = "SKILL.md"
NAME_MAX_LENGTH = 64
DESCRIPTION_MAX_LENGTH = 1024
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

SCAFFOLD_TEMPLATE = """---
name: {name}
description: Describe when this skill applies and what it changes.
---

Write the skill instructions here.
"""


class SkillValidationError(ValueError):
    """Invalid SKILL.md content; `errors` lists every failed rule."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _name_errors(name: str) -> list[str]:
    errors: list[str] = []
    if len(name) > NAME_MAX_LENGTH:
        errors.append(f"name exceeds {NAME_MAX_LENGTH} characters")
    if not NAME_PATTERN.fullmatch(name):
        errors.append("name must match ^[a-z0-9]+(-[a-z0-9]+)*$")
    return errors


def _split_frontmatter(text: str) -> tuple[dict, str, str]:
    """Split SKILL.md text into (frontmatter, body, error).

    A non-empty error means the fences or the yaml block are broken and
    frontmatter/body are unusable.
    """
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return {}, "", "missing frontmatter fence"
    for index in range(1, len(lines)):
        if lines[index].strip() != "---":
            continue
        try:
            meta = yaml.safe_load("\n".join(lines[1:index])) or {}
        except yaml.YAMLError as error:
            return {}, "", f"invalid frontmatter yaml: {error}"
        if not isinstance(meta, dict):
            return {}, "", "frontmatter is not a mapping"
        return meta, "\n".join(lines[index + 1 :]), ""
    return {}, "", "unterminated frontmatter fence"


def validate_skill(name: str, text: str) -> tuple[dict, str, list[str]]:
    """Validate SKILL.md content for the skill directory `name`.

    Returns (frontmatter, body, errors); an empty errors list means the
    skill is valid. Fields beyond name and description are not checked.
    """
    meta, body, fence_error = _split_frontmatter(text)
    if fence_error:
        return meta, body, [fence_error]
    errors: list[str] = []
    frontmatter_name = meta.get("name")
    if not isinstance(frontmatter_name, str) or not frontmatter_name:
        errors.append("frontmatter is missing name")
    else:
        errors.extend(_name_errors(frontmatter_name))
        if frontmatter_name != name:
            errors.append(f"name does not match directory name: {name}")
    description = meta.get("description")
    if not isinstance(description, str) or not description:
        errors.append("frontmatter is missing description")
    elif len(description) > DESCRIPTION_MAX_LENGTH:
        errors.append(f"description exceeds {DESCRIPTION_MAX_LENGTH} characters")
    if not body.strip():
        errors.append("empty body")
    return meta, body, errors


class SkillsManager:
    def __init__(self, root: Path, skills_config: dict[str, SkillConfig]) -> None:
        self._skills_dir = root / "skills"
        self._config = skills_config

    def _skill_path(self, name: str) -> Path:
        return self._skills_dir / name / SKILL_FILE

    def _load(self, name: str) -> tuple[dict, str, list[str]]:
        # A file that vanishes mid-scan or holds non-utf-8 bytes degrades to
        # an invalid skill instead of blowing up listing or agent assembly.
        # utf-8-sig strips the BOM that Windows editors prepend, which would
        # otherwise break the frontmatter fence with a misleading error.
        path = self._skill_path(name)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as error:
            return {}, "", [f"unreadable file: {error}"]
        return validate_skill(name, text)

    def list_skills(self) -> list[dict]:
        rows: dict[str, dict] = {}
        if self._skills_dir.is_dir():
            for directory in self._skills_dir.iterdir():
                if not (directory / SKILL_FILE).is_file():
                    continue
                name = directory.name
                meta, _, errors = self._load(name)
                description = meta.get("description")
                config = self._config.get(name, SkillConfig())
                rows[name] = {
                    "name": name,
                    "description": description if isinstance(description, str) else "",
                    "enabled": config.enabled,
                    "confirmed": config.confirmed,
                    "valid": not errors,
                    "errors": errors,
                }
        for name, config in self._config.items():
            if name not in rows:
                rows[name] = {
                    "name": name,
                    "description": "",
                    "enabled": config.enabled,
                    "confirmed": config.confirmed,
                    "valid": False,
                    "errors": ["missing"],
                }
        return [rows[name] for name in sorted(rows)]

    def _qualifying(self) -> list[tuple[str, str]]:
        """(name, description) of every enabled + confirmed + valid skill."""
        result: list[tuple[str, str]] = []
        for name in sorted(self._config):
            config = self._config[name]
            if not (config.enabled and config.confirmed):
                continue
            if not self._skill_path(name).is_file():
                continue
            meta, _, errors = self._load(name)
            if errors:
                continue
            # Fold whitespace so a multi-line description cannot forge
            # extra list entries or instruction lines in the prompt block.
            result.append((name, " ".join(str(meta.get("description")).split())))
        return result

    def prompt_block(self) -> str:
        skills = self._qualifying()
        if not skills:
            return ""
        lines = [
            "Skills available to you. Before applying one, call the "
            "use_skill tool with its name to load the full instructions:"
        ]
        lines.extend(f"- {name}: {description}" for name, description in skills)
        return "\n".join(lines)

    def use_skill(self, name: str) -> str:
        config = self._config.get(name, SkillConfig())
        if not config.enabled:
            raise ToolError(f"skill not enabled: {name}")
        if not config.confirmed:
            raise ToolError(f"skill not confirmed: {name}")
        if not self._skill_path(name).is_file():
            raise ToolError(f"skill missing on disk: {name}")
        _, body, errors = self._load(name)
        if errors:
            raise ToolError(f"skill invalid: {name} ({'; '.join(errors)})")
        return body.strip()

    def agent_tools(self) -> list[AgentTool]:
        if not self._qualifying():
            return []

        def handler(arguments: dict) -> str:
            return self.use_skill(str(arguments.get("name", "")))

        return [
            AgentTool(
                name="use_skill",
                description=(
                    "Load the full instructions of an available skill by name."
                ),
                parameters={
                    "name": {
                        "type": "string",
                        "required": True,
                        "description": "Name of the skill to load.",
                    }
                },
                handler=handler,
            )
        ]

    def read(self, name: str) -> str:
        # An off-pattern name cannot be a skill; treating it as not found
        # also blocks path traversal out of the skills directory.
        path = self._skill_path(name)
        if _name_errors(name) or not path.is_file():
            raise FileNotFoundError(f"skill not found: {name}")
        return path.read_text(encoding="utf-8-sig")

    def write(self, name: str, content: str) -> None:
        # Deliberately PUT-as-create: writing a name that has no directory
        # yet materializes it, unlike create() which rejects duplicates.
        # Validation ties the frontmatter name to the directory name, which
        # also transitively enforces the path-safety rule of read().
        _, _, errors = validate_skill(name, content)
        if errors:
            raise SkillValidationError(errors)
        path = self._skill_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def create(self, name: str) -> None:
        errors = _name_errors(name)
        if errors:
            raise SkillValidationError(errors)
        directory = self._skills_dir / name
        if directory.exists():
            raise FileExistsError(f"skill already exists: {name}")
        directory.mkdir(parents=True)
        (directory / SKILL_FILE).write_text(
            SCAFFOLD_TEMPLATE.format(name=name), encoding="utf-8"
        )

    def import_content(self, content: str) -> str:
        """Create a skill from a full SKILL.md, deriving the name from its
        frontmatter. Rejects a broken/invalid document (SkillValidationError)
        or a name that already exists on disk (FileExistsError). Returns the
        created skill name."""
        meta, _, fence_error = _split_frontmatter(content)
        if fence_error:
            raise SkillValidationError([fence_error])
        name = meta.get("name")
        if not isinstance(name, str) or not name:
            raise SkillValidationError(["frontmatter is missing name"])
        errors = validate_skill(name, content)[2]
        if errors:
            raise SkillValidationError(errors)
        directory = self._skills_dir / name
        if directory.exists():
            raise FileExistsError(f"skill already exists: {name}")
        directory.mkdir(parents=True)
        (directory / SKILL_FILE).write_text(content, encoding="utf-8")
        return name

    def delete(self, name: str) -> None:
        directory = self._skills_dir / name
        if _name_errors(name) or not directory.is_dir():
            raise FileNotFoundError(f"skill not found: {name}")
        shutil.rmtree(directory)


_active: SkillsManager | None = None


def set_active(manager: SkillsManager | None) -> None:
    global _active
    _active = manager


def active_prompt_block() -> str:
    if _active is None:
        return ""
    return _active.prompt_block()


def active_tools() -> list[AgentTool]:
    if _active is None:
        return []
    return _active.agent_tools()


def active_manager() -> SkillsManager | None:
    return _active
