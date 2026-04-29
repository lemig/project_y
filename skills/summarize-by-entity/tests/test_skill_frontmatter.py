"""Frontmatter contract tests for the summarize-by-entity skill.

Asserts the SKILL.md parses, the YAML carries every key the harness
relies on, the values point at the right places, and the resolver regex
compiles. This is a structural test — it does not run the resolver
against briefs (see `test_resolver.py`) or run the skill end-to-end
(see `test_integration.py`).
"""

from __future__ import annotations

import re

import pytest

from skills.skill import SkillFrontmatter

EXPECTED_KEYS = {
    "name",
    "version",
    "owner",
    "resolver",
    "output_schema_ref",
    "verifier",
    "tests_dir",
}


class TestFrontmatter:
    def test_yaml_parses(self, parsed_skill) -> None:
        assert isinstance(parsed_skill["frontmatter"], dict)
        assert parsed_skill["body"].strip(), "methodology body must not be empty"

    def test_all_seven_keys_present(self, parsed_skill) -> None:
        fm = parsed_skill["frontmatter"]
        assert set(fm.keys()) == EXPECTED_KEYS, (
            f"frontmatter keys mismatch — extras: {set(fm) - EXPECTED_KEYS}, "
            f"missing: {EXPECTED_KEYS - set(fm)}"
        )

    def test_validates_against_pydantic_model(self, parsed_skill) -> None:
        fm = SkillFrontmatter(**parsed_skill["frontmatter"])
        assert fm.name == "summarize-by-entity"
        assert fm.version == "v1"
        assert fm.output_schema_ref == "schema.note.Note"
        assert fm.verifier == "verifier.substring_quote"
        assert fm.tests_dir == "skills/summarize-by-entity/tests"

    def test_owner_looks_like_email(self, parsed_skill) -> None:
        owner = parsed_skill["frontmatter"]["owner"]
        assert re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", owner), (
            f"owner must look like an email address, got: {owner!r}"
        )

    def test_resolver_compiles(self, parsed_skill) -> None:
        resolver = parsed_skill["frontmatter"]["resolver"]
        try:
            re.compile(resolver)
        except re.error as e:
            pytest.fail(f"resolver regex did not compile: {e}")

    def test_resolver_is_case_insensitive(self, parsed_skill) -> None:
        # We rely on (?i) for matching across analyst capitalisation styles
        # — uppercase headlines, lowercase chat-style briefs, ALL CAPS pasted
        # subject lines. If the resolver is ever rewritten without case
        # insensitivity, this guard catches the regression at PR time.
        resolver = parsed_skill["frontmatter"]["resolver"]
        compiled = re.compile(resolver)
        assert compiled.flags & re.IGNORECASE, (
            "resolver must be case-insensitive (use inline (?i) or re.IGNORECASE)"
        )
