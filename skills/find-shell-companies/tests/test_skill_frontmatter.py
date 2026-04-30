"""SKILL.md frontmatter validation for find-shell-companies.

Pins the contract enforced by `src/skills/skill.py:SkillFrontmatter`:
the YAML block parses, all 7 required keys are present with the expected
identity (name/version/owner/output_schema_ref/verifier/tests_dir), and the
resolver compiles as a regex. The body is non-empty.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from skills.skill import SkillFrontmatter

_SKILL_DIR = Path(__file__).resolve().parent.parent
_SKILL_PATH = _SKILL_DIR / "SKILL.md"
_FRONTMATTER_OPEN = "---\n"
_FRONTMATTER_CLOSE = "\n---\n"

_REQUIRED_KEYS = {
    "name",
    "version",
    "owner",
    "resolver",
    "output_schema_ref",
    "verifier",
    "tests_dir",
}


def _read_skill() -> tuple[str, str]:
    raw = _SKILL_PATH.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    assert raw.startswith(_FRONTMATTER_OPEN), "SKILL.md must open with a '---' YAML frontmatter block"
    end = raw.find(_FRONTMATTER_CLOSE, len(_FRONTMATTER_OPEN))
    assert end >= 0, "SKILL.md frontmatter has no closing '---' delimiter"
    front = raw[len(_FRONTMATTER_OPEN) : end]
    body = raw[end + len(_FRONTMATTER_CLOSE) :]
    return front, body


def test_skill_md_exists() -> None:
    assert _SKILL_PATH.is_file(), f"missing {_SKILL_PATH}"


def test_frontmatter_yaml_parses_to_mapping() -> None:
    front, _ = _read_skill()
    parsed = yaml.safe_load(front)
    assert isinstance(parsed, dict), "frontmatter must be a YAML mapping"


def test_frontmatter_has_all_seven_required_keys() -> None:
    front, _ = _read_skill()
    parsed = yaml.safe_load(front)
    assert set(parsed.keys()) == _REQUIRED_KEYS, (
        f"frontmatter keys must be exactly {_REQUIRED_KEYS}; got {set(parsed.keys())}"
    )


def test_frontmatter_validates_against_skill_frontmatter_model() -> None:
    front, _ = _read_skill()
    parsed = yaml.safe_load(front)
    fm = SkillFrontmatter(**parsed)  # frozen, extra=forbid — full schema gate
    assert fm.name == "find-shell-companies"
    assert fm.version == "v1"
    assert fm.output_schema_ref == "schema.note.Note"
    assert fm.verifier == "verifier.substring_quote"
    assert fm.tests_dir == "skills/find-shell-companies/tests"


def test_frontmatter_resolver_compiles_as_regex() -> None:
    front, _ = _read_skill()
    parsed = yaml.safe_load(front)
    # If this raises, the planner can never route briefs to this skill.
    re.compile(parsed["resolver"])


def test_frontmatter_owner_looks_like_olaf_email() -> None:
    front, _ = _read_skill()
    parsed = yaml.safe_load(front)
    # Loose check — the schema only requires non-empty; this guards against
    # accidentally shipping a placeholder like 'TODO'.
    assert "@" in parsed["owner"], "owner should be an email address"
    assert parsed["owner"].endswith("@ec.europa.eu"), (
        "owner should be a Commission (@ec.europa.eu) address"
    )


def test_skill_body_is_substantive() -> None:
    _, body = _read_skill()
    assert len(body.strip()) > 500, "SKILL.md body must contain methodology, not just frontmatter"


def test_skill_body_cites_public_sources() -> None:
    """Per CLAUDE.md, skills cite public methodology — FATF / OECD / StAR / ICIJ /
    ACFE — not OLAF-internal procedures. Guard against accidentally shipping
    a body that lost its source-citation block."""
    _, body = _read_skill()
    body_lower = body.lower()
    cited = [
        src for src in ("fatf", "icij", "oecd", "star", "acfe", "egmont")
        if src in body_lower
    ]
    assert len(cited) >= 2, (
        f"SKILL.md body must cite ≥2 public methodology sources; found: {cited}"
    )


def test_skill_body_does_not_leak_olaf_internal_keywords() -> None:
    """Per CLAUDE.md, OLAF-specific operational details stay out of skills.
    This is a coarse string guard — it does not certify the body, but it
    catches the obvious mistake of pasting an internal SOP."""
    _, body = _read_skill()
    body_lower = body.lower()
    forbidden = ["olaf-internal", "olaf internal", "case file", "ocm reference"]
    leaks = [kw for kw in forbidden if kw in body_lower]
    assert not leaks, f"SKILL.md body must not leak OLAF-internal keywords; found: {leaks}"
