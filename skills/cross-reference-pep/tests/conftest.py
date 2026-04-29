"""Shared fixtures for cross-reference-pep skill tests.

Loads SKILL.md once, splits frontmatter and body, exposes both as
fixtures. Keeps the YAML parser in one place so all three test modules
agree on what the skill says.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_SKILL_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"

# Standard markdown frontmatter delimiter: opening "---" on its own
# line, body, closing "---" on its own line, then the body.
_FRONTMATTER_RE = re.compile(
    r"\A---\r?\n(?P<fm>.*?)\r?\n---\r?\n(?P<body>.*)\Z",
    re.DOTALL,
)


def _read_skill() -> tuple[dict, str]:
    raw = _SKILL_PATH.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(raw)
    if match is None:
        raise AssertionError(f"SKILL.md at {_SKILL_PATH} has no YAML frontmatter block")
    fm = yaml.safe_load(match.group("fm"))
    if not isinstance(fm, dict):
        raise AssertionError("SKILL.md frontmatter did not parse to a mapping")
    return fm, match.group("body")


@pytest.fixture(scope="session")
def skill_frontmatter() -> dict:
    fm, _ = _read_skill()
    return fm


@pytest.fixture(scope="session")
def skill_body() -> str:
    _, body = _read_skill()
    return body


@pytest.fixture(scope="session")
def skill_path() -> Path:
    return _SKILL_PATH
