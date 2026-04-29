"""Shared helpers for find-money-flow skill tests.

The repo doesn't (yet) ship a YAML dependency or a SKILL.md loader — those
will arrive with the harness adapter's `load_skill` implementation. For the
v2 starter skill we need only a frontmatter splitter + a flat-string YAML
parser sufficient for the locked frontmatter shape (7 string fields).
"""

from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_MD = SKILL_DIR / "SKILL.md"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_yaml, body) from a `---`-fenced markdown file."""
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with a '---' frontmatter fence")
    rest = text[len("---\n"):]
    end = rest.find("\n---\n")
    if end < 0:
        raise ValueError("SKILL.md frontmatter has no closing '---' fence")
    return rest[:end], rest[end + len("\n---\n"):]


def parse_flat_yaml(yaml_text: str) -> dict[str, str]:
    """Parse the locked flat `key: value` frontmatter shape.

    Deliberately restrictive — rejects nested mappings, lists, comments,
    and empty values. The locked SkillFrontmatter is a flat dict of
    non-empty strings; anything else is a contract violation we want
    to surface as a parse error rather than silently coerce.
    """
    out: dict[str, str] = {}
    for raw in yaml_text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.lstrip() != line:
            raise ValueError(f"unexpected indentation in frontmatter: {raw!r}")
        if ":" not in line:
            raise ValueError(f"frontmatter line missing ':': {raw!r}")
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"empty key in frontmatter: {raw!r}")
        if not value:
            raise ValueError(f"empty value in frontmatter for key {key!r}")
        if key in out:
            raise ValueError(f"duplicate frontmatter key: {key!r}")
        out[key] = value
    return out
