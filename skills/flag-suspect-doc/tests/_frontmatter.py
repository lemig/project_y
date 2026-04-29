"""Minimal frontmatter parser for SKILL.md test scaffolding.

Skill frontmatter uses a strict shape: a leading `---` line, a block of
`key: value` lines (single-line scalar string values only — no nested YAML),
then a closing `---` line, then the markdown body. Keeping the parser
in-test (no pyyaml dep) avoids broadening project deps just to validate the
skill's own contract.

If the project later grows a real skill loader, these tests should switch to
import it. Until then this helper IS the test-side contract.
"""

from __future__ import annotations

from pathlib import Path

_FENCE = "---"


def parse_skill_md(path: Path) -> tuple[dict[str, str], str]:
    """Return (frontmatter_dict, body) for a SKILL.md file.

    Raises ValueError on a malformed file rather than silently returning
    empty data — frontmatter shape is a hard contract.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        raise ValueError(f"{path} does not start with a '---' frontmatter fence")

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            end_idx = i
            break
    if end_idx is None:
        raise ValueError(f"{path} has no closing '---' frontmatter fence")

    fm: dict[str, str] = {}
    for raw in lines[1:end_idx]:
        line = raw.rstrip()
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"{path}: malformed frontmatter line: {line!r}")
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"{path}: blank frontmatter key in line: {line!r}")
        if key in fm:
            raise ValueError(f"{path}: duplicate frontmatter key {key!r}")
        fm[key] = value

    body = "\n".join(lines[end_idx + 1 :])
    return fm, body
