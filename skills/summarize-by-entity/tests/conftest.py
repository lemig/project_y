"""Shared test fixtures for the summarize-by-entity skill.

Makes the skill's tests runnable on their own
(`pytest skills/summarize-by-entity/`) without depending on the repo-root
`pyproject.toml`'s `pythonpath = ["src"]` config. The skill is a
self-contained unit; its tests should work whether invoked from the repo
root or from inside the skill directory.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TypedDict

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

SKILL_DIR = _REPO_ROOT / "skills" / "summarize-by-entity"
SKILL_MD = SKILL_DIR / "SKILL.md"
FIXTURES_DIR = SKILL_DIR / "tests" / "fixtures"


class ParsedSkill(TypedDict):
    frontmatter: dict
    body: str


def parse_skill_md(path: Path) -> ParsedSkill:
    """Split a SKILL.md file into YAML frontmatter (dict) and methodology body (str).

    A SKILL.md file starts with a `---` line, then YAML, then a closing
    `---` line, then the markdown body. Anything else is malformed.
    """
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError(f"{path}: missing opening '---' frontmatter fence")
    end = raw.find("\n---\n", 4)
    if end == -1:
        raise ValueError(f"{path}: missing closing '---' frontmatter fence")
    fm_raw = raw[4:end]
    body = raw[end + len("\n---\n") :]
    fm = yaml.safe_load(fm_raw)
    if not isinstance(fm, dict):
        raise ValueError(f"{path}: frontmatter is not a YAML mapping")
    return {"frontmatter": fm, "body": body}


@pytest.fixture(scope="session")
def parsed_skill() -> ParsedSkill:
    return parse_skill_md(SKILL_MD)
