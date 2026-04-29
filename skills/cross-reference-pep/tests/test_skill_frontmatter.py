"""Frontmatter contract for cross-reference-pep@v1.

Verifies the SKILL.md frontmatter parses cleanly, populates exactly the
seven keys required by ``SkillFrontmatter``, references the locked
output schema and the canonical substring-quote verifier, and that the
resolver regex compiles. Schema drift in src/skills/skill.py will fail
loudly here.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from skills.skill import SkillFrontmatter

_REQUIRED_KEYS = {
    "name",
    "version",
    "owner",
    "resolver",
    "output_schema_ref",
    "verifier",
    "tests_dir",
}


def test_frontmatter_has_exactly_required_keys(skill_frontmatter: dict) -> None:
    assert set(skill_frontmatter.keys()) == _REQUIRED_KEYS


def test_frontmatter_validates_against_schema(skill_frontmatter: dict) -> None:
    fm = SkillFrontmatter(**skill_frontmatter)
    assert fm.name == "cross-reference-pep"
    assert fm.version == "v1"
    assert fm.output_schema_ref == "schema.note.Note"
    assert fm.verifier == "verifier.substring_quote"
    assert fm.tests_dir == "skills/cross-reference-pep/tests"


def test_frontmatter_owner_looks_like_email(skill_frontmatter: dict) -> None:
    fm = SkillFrontmatter(**skill_frontmatter)
    assert "@" in fm.owner and "." in fm.owner.split("@", 1)[1]


def test_resolver_compiles_as_regex(skill_frontmatter: dict) -> None:
    fm = SkillFrontmatter(**skill_frontmatter)
    re.compile(fm.resolver)


def test_extra_frontmatter_keys_rejected(skill_frontmatter: dict) -> None:
    polluted = {**skill_frontmatter, "extra_field": "nope"}
    with pytest.raises(ValidationError):
        SkillFrontmatter(**polluted)


def test_skill_id_format(skill_frontmatter: dict) -> None:
    fm = SkillFrontmatter(**skill_frontmatter)
    assert f"{fm.name}@{fm.version}" == "cross-reference-pep@v1"


def test_body_present_and_non_trivial(skill_body: str) -> None:
    assert len(skill_body.strip()) > 500, (
        "Skill body is suspiciously short — methodology must be documented in SKILL.md"
    )


def test_body_marks_v2_as_placeholder(skill_body: str) -> None:
    """v2 ships a flag-only skill; v3 wires in OpenSanctions. The body
    must say so plainly so a reader doesn't mistake a flag for a hit."""
    body_lower = skill_body.lower()
    assert "placeholder" in body_lower
    assert "opensanctions" in body_lower


def test_body_cites_public_methodology(skill_body: str) -> None:
    """CLAUDE.md forbids OLAF-internal methodology in skill bodies. We
    can't enforce that negatively, but we can require explicit public
    citations are present."""
    body_lower = skill_body.lower()
    assert "fatf" in body_lower
    assert "wolfsberg" in body_lower
    assert "recommendation 12" in body_lower or "recommendation 12" in body_lower
