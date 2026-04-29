"""Golden-run replay tests for `DeepAgentsHarness`.

Per CLAUDE.md: *"Pinned exact version. Golden-run replay tests gate dep
upgrades."* This file captures the deterministic, non-LLM output of a fixed
investigation script — skill load order, dispatched skill_ids, the canonical
checkpoint JSON, and the resulting checkpoint id (sha256). If a `deepagents`
or transitive bump changes any of these without an explicit golden regen, CI
fails and a human reviews the diff.

Regen procedure when the change is intentional:

    uv run python -c "
    import os, sys; os.environ['REGEN_GOLDEN']='1';
    sys.exit(__import__('pytest').main(['-x','tests/test_deep_agents_golden.py']))
    "

The regen path writes the new expected values to disk under
`tests/golden/deep_agents/`. Open the diff in your PR; the reviewer's job is
to confirm the change is desired before landing the bump.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from agent.deep_agents_harness import DeepAgentsHarness
from agent.harness import SubagentTask
from schema.brief import Brief

_GOLDEN_DIR = Path(__file__).parent / "golden" / "deep_agents"
_BRIEF_HASH = "c" * 64

# Frozen skill markdown. Same bytes on every machine → same git_sha →
# same checkpoint payload. Don't reformat without regenerating goldens.
_SKILL_MD_TEMPLATE = """---
name: {name}
version: v1
owner: m.cabero@olaf.eu
resolver: {resolver}
output_schema_ref: schema.note.Note
verifier: verifier.substring_quote
tests_dir: tests/skills/{name}
---

# {name}

Frozen body for golden replay. Do not edit without regenerating goldens.
"""


_SCRIPT_BRIEF_TEXT = "Trace the EUR 120,000 transfer from contract X-2026-001."

_SCRIPT_SKILLS: tuple[tuple[str, str], ...] = (
    ("find-money-flow", "money|flow|trace"),
    ("detect-procurement-collusion", "tender|bid|collusion"),
    ("flag-suspect-doc", "suspect|fraud-likelihood"),
)

_SCRIPT_DISPATCH: tuple[str, ...] = (
    "find-money-flow@v1",
    "detect-procurement-collusion@v1",
    "find-money-flow@v1",
    "flag-suspect-doc@v1",
)

_SCRIPT_AGENT_PAYLOAD: dict[str, Any] = {
    "messages": [
        {"role": "user", "content": _SCRIPT_BRIEF_TEXT},
        {"role": "ai", "content": "Plan: dispatch find-money-flow first."},
        {"role": "tool", "content": "ok"},
        {"role": "ai", "content": "Done."},
    ],
}


def _stub_factory(payload: dict[str, Any]) -> Any:
    class _Stub:
        def invoke(self, _state: dict[str, Any]) -> dict[str, Any]:
            return payload

    def factory(**_kwargs: Any) -> _Stub:
        return _Stub()

    return factory


def _write_skills(skills_root: Path) -> None:
    for name, resolver in _SCRIPT_SKILLS:
        d = skills_root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            _SKILL_MD_TEMPLATE.format(name=name, resolver=resolver),
            encoding="utf-8",
        )


def _run_script(tmp_path: Path) -> tuple[DeepAgentsHarness, str]:
    """Execute the fixed investigation script. Returns (harness, checkpoint_id)."""
    skills_root = tmp_path / "skills"
    _write_skills(skills_root)

    h = DeepAgentsHarness(
        skills_root=skills_root,
        checkpoints_dir=tmp_path / "ck",
        model=object(),
        agent_factory=_stub_factory(_SCRIPT_AGENT_PAYLOAD),
    )

    for name, _ in _SCRIPT_SKILLS:
        h.load_skill(f"{name}@v1")

    brief = Brief(text=_SCRIPT_BRIEF_TEXT, corpus_snapshot_hash=_BRIEF_HASH)
    h.planner_run(brief)

    # spawn_subagent is a v2 stub: validates dispatch + records audit state, then
    # raises NotImplementedError. The golden script captures the recorded state.
    bh = brief.compute_hash()
    for skill_id in _SCRIPT_DISPATCH:
        try:
            h.spawn_subagent(
                SubagentTask(skill_id=skill_id, inputs={}, parent_brief_hash=bh)
            )
        except NotImplementedError:
            pass

    cid = h.checkpoint()
    return h, cid


def _golden_path(name: str) -> Path:
    return _GOLDEN_DIR / name


def _read_or_regen(name: str, current: str) -> str:
    """Compare to disk or write the new golden, depending on REGEN_GOLDEN."""
    path = _golden_path(name)
    if os.environ.get("REGEN_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(current, encoding="utf-8")
        return current
    if not path.is_file():
        raise AssertionError(
            f"Golden file {path} missing; run with REGEN_GOLDEN=1 to write it."
        )
    return path.read_text(encoding="utf-8")


def test_golden_skill_load_order(tmp_path: Path) -> None:
    h, _ = _run_script(tmp_path)
    current = json.dumps(h._state.skill_load_log, indent=2) + "\n"
    expected = _read_or_regen("skill_load_order.json", current)
    assert current == expected, "skill load order drifted vs golden"


def test_golden_dispatched_skill_ids(tmp_path: Path) -> None:
    h, _ = _run_script(tmp_path)
    current = json.dumps(h._state.dispatched_skill_ids, indent=2) + "\n"
    expected = _read_or_regen("dispatched_skill_ids.json", current)
    assert current == expected, "dispatched skill_ids drifted vs golden"


def test_golden_checkpoint_payload(tmp_path: Path) -> None:
    _, cid = _run_script(tmp_path)
    payload = (tmp_path / "ck" / f"{cid}.json").read_text(encoding="utf-8")
    expected = _read_or_regen("checkpoint_payload.json", payload + "\n")
    # The +"\n" lets the file end in a newline; payload itself does not.
    assert payload + "\n" == expected, "checkpoint canonical JSON drifted vs golden"


def test_golden_checkpoint_id(tmp_path: Path) -> None:
    _, cid = _run_script(tmp_path)
    expected = _read_or_regen("checkpoint_id.txt", cid + "\n").strip()
    assert cid == expected, "checkpoint sha256 id drifted vs golden"


def test_golden_resume_round_trip_yields_same_checkpoint(tmp_path: Path) -> None:
    """A resume() then re-checkpoint() must reproduce the same id, byte-for-byte."""
    h, cid1 = _run_script(tmp_path)

    # Fresh harness, same checkpoint dir.
    h2 = DeepAgentsHarness(
        skills_root=tmp_path / "skills",
        checkpoints_dir=tmp_path / "ck",
        model=object(),
        agent_factory=_stub_factory(_SCRIPT_AGENT_PAYLOAD),
    )
    h2.resume(cid1)
    cid2 = h2.checkpoint()

    assert cid1 == cid2, "resume() then checkpoint() did not round-trip the id"


@pytest.mark.parametrize(
    "name",
    [
        "skill_load_order.json",
        "dispatched_skill_ids.json",
        "checkpoint_payload.json",
        "checkpoint_id.txt",
    ],
)
def test_golden_files_exist_under_version_control(name: str) -> None:
    """Guard against an accidental delete of a golden file."""
    assert _golden_path(name).is_file(), (
        f"Golden file {name} missing under {_GOLDEN_DIR}. "
        "Run the suite with REGEN_GOLDEN=1 to recreate (and commit the result)."
    )
