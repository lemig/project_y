"""Frontmatter contract for the narrate-fraud-pattern skill.

Pins the YAML frontmatter shape the agent harness will consume when it
loads SKILL.md off disk. Reuses the harness's own parser
(`agent.deep_agents_harness._split_frontmatter` /
`_parse_frontmatter`) so the test fails the moment the parser and
manifest disagree.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent.deep_agents_harness import _parse_frontmatter, _split_frontmatter
from skills.skill import SkillFrontmatter

_SKILL_DIR = Path(__file__).resolve().parent.parent
_SKILL_MD = _SKILL_DIR / "SKILL.md"

_EXPECTED_KEYS = {
    "name",
    "version",
    "owner",
    "resolver",
    "output_schema_ref",
    "verifier",
    "tests_dir",
}


def _load_frontmatter() -> SkillFrontmatter:
    text = _SKILL_MD.read_text(encoding="utf-8-sig")
    front, _body = _split_frontmatter(text)
    return _parse_frontmatter(front)


def test_skill_md_exists() -> None:
    assert _SKILL_MD.is_file(), f"missing manifest: {_SKILL_MD}"


def test_frontmatter_parses() -> None:
    fm = _load_frontmatter()
    assert isinstance(fm, SkillFrontmatter)


def test_all_seven_keys_present() -> None:
    text = _SKILL_MD.read_text(encoding="utf-8-sig")
    front, _ = _split_frontmatter(text)
    import yaml

    parsed = yaml.safe_load(front)
    assert set(parsed.keys()) == _EXPECTED_KEYS, (
        f"frontmatter keys differ from contract: "
        f"missing={_EXPECTED_KEYS - set(parsed.keys())}, "
        f"extra={set(parsed.keys()) - _EXPECTED_KEYS}"
    )


def test_pinned_field_values() -> None:
    fm = _load_frontmatter()
    assert fm.name == "narrate-fraud-pattern"
    assert fm.version == "v1"
    assert fm.owner == "m.cabero@olaf.eu"
    assert fm.output_schema_ref == "schema.note.Note"
    assert fm.verifier == "verifier.substring_quote"
    assert fm.tests_dir == "skills/narrate-fraud-pattern/tests"


def test_resolver_compiles() -> None:
    fm = _load_frontmatter()
    pattern = re.compile(fm.resolver)
    # Smoke-test compile result is usable, not just constructible.
    assert pattern.search("narrate the fraud pattern") is not None


def test_tests_dir_points_at_this_directory() -> None:
    fm = _load_frontmatter()
    repo_root = _SKILL_DIR.parent.parent
    declared = repo_root / fm.tests_dir
    assert declared.resolve() == Path(__file__).resolve().parent
