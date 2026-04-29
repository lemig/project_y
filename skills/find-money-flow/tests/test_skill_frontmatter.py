"""SKILL.md frontmatter contract tests.

Asserts that:
- the file is well-formed (`---`-fenced, parseable),
- every locked `SkillFrontmatter` field is present and non-empty,
- the resolver compiles as a regex,
- the body is non-trivial.
"""

from __future__ import annotations

import re

from pydantic import ValidationError

from skills.skill import SkillFrontmatter

from _find_money_flow_lib import SKILL_MD, parse_flat_yaml, split_frontmatter

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
    assert SKILL_MD.is_file(), f"missing SKILL.md at {SKILL_MD}"


def test_frontmatter_parses() -> None:
    fm_text, body = split_frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    assert fm_text.strip(), "frontmatter is empty"
    assert body.strip(), "SKILL.md body is empty"
    parsed = parse_flat_yaml(fm_text)
    assert set(parsed.keys()) == EXPECTED_KEYS, (
        f"frontmatter keys mismatch: got {sorted(parsed.keys())}, "
        f"expected {sorted(EXPECTED_KEYS)}"
    )


def test_frontmatter_validates_against_pydantic_contract() -> None:
    fm_text, _ = split_frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    parsed = parse_flat_yaml(fm_text)
    fm = SkillFrontmatter(**parsed)  # raises ValidationError on contract drift
    assert fm.name == "find-money-flow"
    assert fm.version == "v1"
    assert fm.output_schema_ref == "schema.note.Note"
    assert fm.verifier == "verifier.substring_quote"
    assert fm.tests_dir == "skills/find-money-flow/tests"
    assert "@" in fm.owner and "olaf" in fm.owner.lower()


def test_resolver_compiles() -> None:
    fm_text, _ = split_frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    parsed = parse_flat_yaml(fm_text)
    # If the resolver doesn't compile, this is a hard contract violation.
    re.compile(parsed["resolver"])


def test_extra_field_in_frontmatter_would_fail_validation() -> None:
    """Self-test: prove that the frozen contract still rejects extras."""
    fm_text, _ = split_frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    parsed = parse_flat_yaml(fm_text)
    parsed["unauthorized"] = "value"
    try:
        SkillFrontmatter(**parsed)
    except ValidationError:
        return
    raise AssertionError(
        "SkillFrontmatter accepted an unauthorized field — contract regression"
    )
