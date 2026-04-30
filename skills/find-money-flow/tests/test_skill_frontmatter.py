"""SKILL.md frontmatter contract tests.

Asserts that:
- the file is well-formed (`---`-fenced, parseable),
- every locked `SkillFrontmatter` field is present and non-empty,
- the resolver compiles as a regex,
- the body is non-trivial.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import ValidationError

from agent.deep_agents_harness import _parse_frontmatter, _split_frontmatter
from skills.skill import SkillFrontmatter

_SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"

EXPECTED_KEYS = {
    "name",
    "version",
    "owner",
    "resolver",
    "output_schema_ref",
    "verifier",
    "tests_dir",
}


def test_skill_md_exists() -> None:
    assert _SKILL_MD.is_file(), f"missing SKILL.md at {_SKILL_MD}"


def test_frontmatter_parses() -> None:
    raw = _SKILL_MD.read_text(encoding="utf-8-sig")
    front, body = _split_frontmatter(raw)
    assert front.strip(), "frontmatter is empty"
    assert body.strip(), "SKILL.md body is empty"


def test_frontmatter_validates_against_pydantic_contract() -> None:
    raw = _SKILL_MD.read_text(encoding="utf-8-sig")
    front, _ = _split_frontmatter(raw)
    fm = _parse_frontmatter(front)
    assert isinstance(fm, SkillFrontmatter)
    assert fm.name == "find-money-flow"
    assert fm.version == "v1"
    assert fm.output_schema_ref == "schema.note.Note"
    assert fm.verifier == "verifier.substring_quote"
    assert fm.tests_dir == "skills/find-money-flow/tests"
    assert "@" in fm.owner and fm.owner.lower().endswith("@ec.europa.eu")


def test_frontmatter_keys_match_locked_set() -> None:
    """The 7 locked keys must all be present (none missing, none extra).

    SkillFrontmatter is `extra="forbid"`, so the validator above already
    rejects extras; this assertion documents the locked keys explicitly so
    a reviewer doesn't have to read the model definition.
    """
    raw = _SKILL_MD.read_text(encoding="utf-8-sig")
    front, _ = _split_frontmatter(raw)
    fm = _parse_frontmatter(front)
    assert set(SkillFrontmatter.model_fields.keys()) == EXPECTED_KEYS
    # And every locked field is populated on this skill's frontmatter.
    assert all(getattr(fm, k) for k in EXPECTED_KEYS)


def test_resolver_compiles() -> None:
    raw = _SKILL_MD.read_text(encoding="utf-8-sig")
    front, _ = _split_frontmatter(raw)
    fm = _parse_frontmatter(front)
    # If the resolver doesn't compile, this is a hard contract violation.
    re.compile(fm.resolver)


def test_extra_field_would_be_rejected() -> None:
    """Self-test: prove that the frozen contract still rejects extras."""
    raw = _SKILL_MD.read_text(encoding="utf-8-sig")
    front, _ = _split_frontmatter(raw)
    fm = _parse_frontmatter(front)
    payload = fm.model_dump()
    payload["unauthorized"] = "value"
    try:
        SkillFrontmatter(**payload)
    except ValidationError:
        return
    raise AssertionError(
        "SkillFrontmatter accepted an unauthorized field — contract regression"
    )
