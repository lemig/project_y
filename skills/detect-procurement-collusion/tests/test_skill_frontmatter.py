"""SKILL.md frontmatter shape test for detect-procurement-collusion.

This is the cheap, no-LLM gate: parse the YAML, verify the seven keys defined
in `src/skills/skill.py:SkillFrontmatter`, and confirm the resolver compiles
as a regex. The Skillify protocol (CLAUDE.md, premise 3) requires every skill
to carry exactly these fields, frontmatter-validated, before anything else
runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from skills.skill import SkillFrontmatter

_SKILL_DIR = Path(__file__).resolve().parents[1]
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_REQUIRED_KEYS = {
    "name",
    "version",
    "owner",
    "resolver",
    "output_schema_ref",
    "verifier",
    "tests_dir",
}


def _read_frontmatter_text() -> str:
    raw = _SKILL_MD.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise AssertionError("SKILL.md does not start with a '---' frontmatter block")
    end = raw.find("\n---\n", len("---\n"))
    if end < 0:
        raise AssertionError("SKILL.md frontmatter has no closing '---' delimiter")
    return raw[len("---\n") : end]


def test_skill_md_exists() -> None:
    assert _SKILL_MD.is_file(), f"SKILL.md missing at {_SKILL_MD}"


def test_frontmatter_yaml_parses() -> None:
    parsed = yaml.safe_load(_read_frontmatter_text())
    assert isinstance(parsed, dict), "frontmatter must be a YAML mapping"


def test_frontmatter_has_all_seven_keys() -> None:
    parsed = yaml.safe_load(_read_frontmatter_text())
    assert set(parsed.keys()) == _REQUIRED_KEYS, (
        f"frontmatter keys mismatch: missing={_REQUIRED_KEYS - parsed.keys()} "
        f"extra={parsed.keys() - _REQUIRED_KEYS}"
    )


def test_frontmatter_validates_against_schema() -> None:
    parsed = yaml.safe_load(_read_frontmatter_text())
    fm = SkillFrontmatter(**parsed)
    # Lock the canonical values the planner / harness contract on.
    assert fm.name == "detect-procurement-collusion"
    assert fm.version == "v1"
    assert fm.output_schema_ref == "schema.note.Note"
    assert fm.verifier == "verifier.substring_quote"
    assert fm.tests_dir == "skills/detect-procurement-collusion/tests"


def test_resolver_compiles_as_regex() -> None:
    parsed = yaml.safe_load(_read_frontmatter_text())
    try:
        re.compile(parsed["resolver"])
    except re.error as exc:  # narrow exception per CLAUDE.md "no except Exception:"
        pytest.fail(f"resolver regex does not compile: {exc}")


def test_owner_is_olaf_email() -> None:
    parsed = yaml.safe_load(_read_frontmatter_text())
    owner = parsed["owner"]
    assert "@" in owner, f"owner must be an email, got {owner!r}"
    # Skill is OLAF-owned per CLAUDE.md; the address points to the OLAF maintainer.
    assert owner.endswith("@olaf.eu"), f"owner must be an @olaf.eu address, got {owner!r}"
