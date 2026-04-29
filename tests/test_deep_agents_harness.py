"""DeepAgentsHarness unit tests.

The LLM is mocked via an `agent_factory` stub so these tests never reach the
network. Live-endpoint behavior is covered by `test_deep_agents_integration.py`
behind the `integration` mark.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from agent.deep_agents_harness import (
    DeepAgentsHarness,
    _git_blob_sha1,
    _HarnessState,
)
from agent.harness import CheckpointId, PlannerResult, SubagentResult, SubagentTask
from schema.brief import Brief

_BRIEF_HASH = "a" * 64
_OTHER_HASH = "b" * 64

_VALID_SKILL_MD = """---
name: find-money-flow
version: v1
owner: m.cabero@olaf.eu
resolver: money|flow|trace
output_schema_ref: schema.note.Note
verifier: verifier.substring_quote
tests_dir: tests/skills/find-money-flow
---

# find-money-flow

Trace funds across documents and entities given a starting account or contract.
"""


def _brief(text: str = "Trace the 120k from contract X.") -> Brief:
    return Brief(text=text, corpus_snapshot_hash=_BRIEF_HASH)


class _StubAgent:
    """Stand-in for a compiled deep-agent graph used in unit tests."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.invocations: list[dict[str, Any]] = []

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        self.invocations.append(state)
        return self._payload


def _stub_factory(payload: dict[str, Any]) -> Any:
    stub = _StubAgent(payload)

    def factory(**_kwargs: Any) -> _StubAgent:
        return stub

    factory.stub = stub
    return factory


def _write_skill(skills_root: Path, name: str, body: str = _VALID_SKILL_MD) -> Path:
    skill_dir = skills_root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(body, encoding="utf-8")
    return path


def _harness(tmp_path: Path, factory: Any | None = None) -> DeepAgentsHarness:
    return DeepAgentsHarness(
        skills_root=tmp_path / "skills",
        checkpoints_dir=tmp_path / "ck",
        model=object(),  # opaque sentinel; the stub factory ignores it
        agent_factory=factory or _stub_factory({"messages": []}),
    )


def test_load_skill_parses_frontmatter_and_pins_git_sha(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    path = _write_skill(skills_root, "find-money-flow")

    h = _harness(tmp_path)
    skill = h.load_skill("find-money-flow@v1")

    assert skill.skill_id == "find-money-flow@v1"
    assert skill.frontmatter.owner == "m.cabero@olaf.eu"
    assert skill.frontmatter.verifier == "verifier.substring_quote"
    assert skill.git_sha == _git_blob_sha1(path.read_bytes())
    assert "find-money-flow" in skill.body


def test_load_skill_rejects_malformed_skill_id(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    with pytest.raises(ValueError, match="must match"):
        h.load_skill("no-version")
    with pytest.raises(ValueError, match="must match"):
        h.load_skill("@v1")


def test_load_skill_missing_file(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    with pytest.raises(FileNotFoundError):
        h.load_skill("not-a-skill@v1")


def test_load_skill_rejects_frontmatter_name_mismatch(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "find-money-flow")
    h = _harness(tmp_path)
    # the file lives at find-money-flow/, but caller asks for a different name
    skills_root_other = skills_root / "decoy" / "SKILL.md"
    skills_root_other.parent.mkdir(parents=True, exist_ok=True)
    skills_root_other.write_text(_VALID_SKILL_MD, encoding="utf-8")
    with pytest.raises(ValueError, match="disagrees with frontmatter name"):
        h.load_skill("decoy@v1")


def test_load_skill_rejects_frontmatter_version_mismatch(tmp_path: Path) -> None:
    _write_skill(tmp_path / "skills", "find-money-flow")
    h = _harness(tmp_path)
    with pytest.raises(ValueError, match="disagrees with frontmatter version"):
        h.load_skill("find-money-flow@v9")


def test_load_skill_records_load_order_and_dedupes(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "find-money-flow")
    second = _VALID_SKILL_MD.replace("name: find-money-flow", "name: detect-collusion")
    _write_skill(skills_root, "detect-collusion", body=second)

    h = _harness(tmp_path)
    h.load_skill("find-money-flow@v1")
    h.load_skill("detect-collusion@v1")
    h.load_skill("find-money-flow@v1")  # idempotent

    assert h._state.skill_load_log == ["find-money-flow@v1", "detect-collusion@v1"]


def test_planner_run_returns_planner_result_and_records_state(tmp_path: Path) -> None:
    factory = _stub_factory(
        {"messages": [{"role": "user", "content": "x"}, {"role": "ai", "content": "ok"}]}
    )
    h = _harness(tmp_path, factory=factory)

    brief = _brief()
    pr = h.planner_run(brief)

    assert isinstance(pr, PlannerResult)
    assert pr.notes == ()
    assert pr.plan_log == ("user", "ai")
    assert h._state.last_brief_hash == brief.compute_hash()
    assert h._state.plan_log == ["user", "ai"]
    # the stub agent saw exactly the brief text as the user message
    assert factory.stub.invocations == [
        {"messages": [{"role": "user", "content": brief.text}]}
    ]


def test_planner_run_uses_env_model_when_none_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def factory(**kwargs: Any) -> _StubAgent:
        captured.update(kwargs)
        return _StubAgent({"messages": []})

    monkeypatch.setenv("LLM_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "gemma-4-9b-it")

    h = DeepAgentsHarness(
        skills_root=tmp_path / "skills",
        checkpoints_dir=tmp_path / "ck",
        model=None,  # force env-var path
        agent_factory=factory,
    )
    h.planner_run(_brief())

    # ChatOpenAI was constructed from env and handed to the factory
    model = captured["model"]
    assert model.__class__.__name__ == "ChatOpenAI"
    assert str(model.openai_api_base) == "http://example.invalid/v1"
    assert model.model_name == "gemma-4-9b-it"


def test_planner_run_missing_env_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    h = DeepAgentsHarness(
        skills_root=tmp_path / "skills",
        checkpoints_dir=tmp_path / "ck",
        model=None,
        agent_factory=_stub_factory({"messages": []}),
    )
    with pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        h.planner_run(_brief())


def test_spawn_subagent_dispatches_by_skill_id(tmp_path: Path) -> None:
    _write_skill(tmp_path / "skills", "find-money-flow")
    h = _harness(tmp_path)

    task = SubagentTask(
        skill_id="find-money-flow@v1",
        inputs={"starting_account": "BE12 1234"},
        parent_brief_hash=_BRIEF_HASH,
    )
    sr = h.spawn_subagent(task)

    assert isinstance(sr, SubagentResult)
    assert sr.skill_id == "find-money-flow@v1"
    assert sr.notes == ()
    # skill_version is the file's git blob SHA-1
    expected_sha = _git_blob_sha1(
        (tmp_path / "skills" / "find-money-flow" / "SKILL.md").read_bytes()
    )
    assert sr.skill_version == expected_sha
    assert h._state.dispatched_skill_ids == ["find-money-flow@v1"]


def test_spawn_subagent_records_dispatch_order(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "find-money-flow")
    second = _VALID_SKILL_MD.replace("name: find-money-flow", "name: detect-collusion")
    _write_skill(skills_root, "detect-collusion", body=second)

    h = _harness(tmp_path)
    for sid in ("detect-collusion@v1", "find-money-flow@v1", "detect-collusion@v1"):
        h.spawn_subagent(
            SubagentTask(skill_id=sid, inputs={}, parent_brief_hash=_BRIEF_HASH)
        )

    assert h._state.dispatched_skill_ids == [
        "detect-collusion@v1",
        "find-money-flow@v1",
        "detect-collusion@v1",
    ]


def test_checkpoint_round_trip_restores_state(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "find-money-flow")
    factory = _stub_factory({"messages": [{"role": "user", "content": "x"}]})
    h = _harness(tmp_path, factory=factory)

    brief = _brief()
    h.planner_run(brief)
    h.spawn_subagent(
        SubagentTask(skill_id="find-money-flow@v1", inputs={}, parent_brief_hash=_BRIEF_HASH)
    )
    cid = h.checkpoint()

    # second harness, fresh state — recovers the prior state byte-for-byte
    h2 = _harness(tmp_path, factory=_stub_factory({"messages": []}))
    h2.resume(cid)

    assert h2._state.skill_load_log == ["find-money-flow@v1"]
    assert h2._state.dispatched_skill_ids == ["find-money-flow@v1"]
    assert h2._state.plan_log == ["user"]
    assert h2._state.last_brief_hash == brief.compute_hash()


def test_checkpoint_id_is_content_addressable(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    h._state.skill_load_log = ["a@v1", "b@v2"]
    cid = h.checkpoint()

    payload = (tmp_path / "ck" / f"{cid}.json").read_text()
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == cid

    parsed = json.loads(payload)
    assert parsed["skill_load_log"] == ["a@v1", "b@v2"]


def test_checkpoint_canonical_serialization_is_stable() -> None:
    s = _HarnessState(
        skill_load_log=["a@v1"],
        dispatched_skill_ids=["a@v1", "b@v1"],
        plan_log=["user", "ai", "tool"],
        last_brief_hash=_BRIEF_HASH,
    )
    # JSON is sorted-keys, no whitespace, UTF-8 unescaped — golden-stable.
    expected = (
        '{"dispatched_skill_ids":["a@v1","b@v1"],'
        f'"last_brief_hash":"{_BRIEF_HASH}",'
        '"plan_log":["user","ai","tool"],'
        '"skill_load_log":["a@v1"]}'
    )
    assert s.to_canonical_json() == expected
    # round-trips losslessly
    assert _HarnessState.from_canonical_json(expected).to_canonical_json() == expected


def test_resume_unknown_checkpoint_raises(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    with pytest.raises(FileNotFoundError):
        h.resume(CheckpointId("0" * 64))


def test_git_blob_sha1_matches_git_hash_object() -> None:
    # `git hash-object` of the empty blob is a well-known constant.
    assert _git_blob_sha1(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    # And of "hello\n".
    assert _git_blob_sha1(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
