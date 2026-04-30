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
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from agent.deep_agents_harness import (
    CheckpointIntegrityError,
    DeepAgentsHarness,
    _git_blob_sha1,
    _HarnessState,
    _extract_notes,
    _extract_plan_log,
    _parse_frontmatter,
    _split_frontmatter,
)
from agent.harness import CheckpointId, PlannerResult, SubagentTask
from schema.brief import Brief

_BRIEF_HASH = "a" * 64
_OTHER_HASH = "b" * 64

_VALID_SKILL_MD = """---
name: find-money-flow
version: v1
owner: miguel.cabero@ec.europa.eu
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


def _harness_with_brief(tmp_path: Path, brief: Brief) -> tuple[DeepAgentsHarness, Brief]:
    """Build a harness and run planner_run so spawn_subagent has a brief in scope."""
    h = _harness(tmp_path, factory=_stub_factory({"messages": [{"role": "user", "content": brief.text}]}))
    h.planner_run(brief)
    return h, brief


# -----------------------------------------------------------------------------
# load_skill
# -----------------------------------------------------------------------------


def test_load_skill_parses_frontmatter_and_pins_git_sha(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    path = _write_skill(skills_root, "find-money-flow")

    h = _harness(tmp_path)
    skill = h.load_skill("find-money-flow@v1")

    assert skill.skill_id == "find-money-flow@v1"
    assert skill.frontmatter.owner == "miguel.cabero@ec.europa.eu"
    assert skill.frontmatter.verifier == "verifier.substring_quote"
    assert skill.git_sha == _git_blob_sha1(path.read_bytes())
    assert "find-money-flow" in skill.body
    assert h._state.loaded_skill_shas == {"find-money-flow@v1": skill.git_sha}


def test_load_skill_rejects_malformed_skill_id(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    with pytest.raises(ValueError, match="must match"):
        h.load_skill("no-version")
    with pytest.raises(ValueError, match="must match"):
        h.load_skill("@v1")
    with pytest.raises(ValueError, match="must match"):
        h.load_skill("../etc/passwd@v1")  # path-traversal attempt rejected by regex


def test_load_skill_missing_file(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    with pytest.raises(FileNotFoundError):
        h.load_skill("not-a-skill@v1")


def test_load_skill_rejects_frontmatter_name_mismatch(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    decoy = skills_root / "decoy" / "SKILL.md"
    decoy.parent.mkdir(parents=True, exist_ok=True)
    decoy.write_text(_VALID_SKILL_MD, encoding="utf-8")  # frontmatter says find-money-flow

    h = _harness(tmp_path)
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
    h.load_skill("find-money-flow@v1")  # idempotent — pinned SHA matches

    assert h._state.skill_load_log == ["find-money-flow@v1", "detect-collusion@v1"]
    assert set(h._state.loaded_skill_shas.keys()) == {
        "find-money-flow@v1",
        "detect-collusion@v1",
    }


def test_load_skill_detects_drift_when_disk_bytes_change(tmp_path: Path) -> None:
    """SKILL.md edited mid-investigation must not be silently re-pinned."""
    skills_root = tmp_path / "skills"
    path = _write_skill(skills_root, "find-money-flow")
    h = _harness(tmp_path)
    h.load_skill("find-money-flow@v1")

    # Same skill_id, different bytes -> different git_sha
    edited = _VALID_SKILL_MD.replace("Trace funds", "Trace funds [edited]")
    path.write_text(edited, encoding="utf-8")

    with pytest.raises(ValueError, match="drift"):
        h.load_skill("find-money-flow@v1")


def test_load_skill_tolerates_crlf_line_endings(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "find-money-flow"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_bytes(_VALID_SKILL_MD.replace("\n", "\r\n").encode("utf-8"))

    h = _harness(tmp_path)
    skill = h.load_skill("find-money-flow@v1")
    assert skill.frontmatter.name == "find-money-flow"


def test_load_skill_tolerates_utf8_bom(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "find-money-flow"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_bytes(b"\xef\xbb\xbf" + _VALID_SKILL_MD.encode("utf-8"))

    h = _harness(tmp_path)
    skill = h.load_skill("find-money-flow@v1")
    assert skill.frontmatter.name == "find-money-flow"


def test_load_skill_rejects_oversize_file(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "find-money-flow"
    skill_dir.mkdir(parents=True, exist_ok=True)
    # Pad the body with > 1 MiB of fluff
    bloated = _VALID_SKILL_MD + "x" * (1 << 20 + 1)
    (skill_dir / "SKILL.md").write_text(bloated, encoding="utf-8")

    h = _harness(tmp_path)
    with pytest.raises(ValueError, match="exceeds size cap"):
        h.load_skill("find-money-flow@v1")


def test_load_skill_rejects_non_utf8_bytes(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "find-money-flow"
    skill_dir.mkdir(parents=True, exist_ok=True)
    # Latin-1 byte that's not valid UTF-8 in this position
    (skill_dir / "SKILL.md").write_bytes(b"\xff\xfe garbage")

    h = _harness(tmp_path)
    with pytest.raises(ValueError, match="not valid UTF-8"):
        h.load_skill("find-money-flow@v1")


# -----------------------------------------------------------------------------
# _split_frontmatter / _parse_frontmatter
# -----------------------------------------------------------------------------


def test_split_frontmatter_rejects_missing_opening_delimiter() -> None:
    with pytest.raises(ValueError, match="must start with"):
        _split_frontmatter("no frontmatter here\n")


def test_split_frontmatter_rejects_missing_closing_delimiter() -> None:
    with pytest.raises(ValueError, match="no closing"):
        _split_frontmatter("---\nname: x\nbody but no closing delimiter\n")


def test_parse_frontmatter_rejects_non_dict_yaml() -> None:
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        _parse_frontmatter("- a\n- b\n")


# -----------------------------------------------------------------------------
# planner_run
# -----------------------------------------------------------------------------


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
    assert factory.stub.invocations == [
        {"messages": [{"role": "user", "content": brief.text}]}
    ]


def test_planner_run_caches_constructed_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When model=None, the env-built ChatOpenAI is built once and reused."""
    monkeypatch.setenv("LLM_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "gemma-4-9b-it")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    captured_models: list[Any] = []

    def factory(**kwargs: Any) -> _StubAgent:
        captured_models.append(kwargs.get("model"))
        return _StubAgent({"messages": []})

    h = DeepAgentsHarness(
        skills_root=tmp_path / "skills",
        checkpoints_dir=tmp_path / "ck",
        model=None,
        agent_factory=factory,
    )
    h.planner_run(_brief())
    h.planner_run(_brief())

    assert len(captured_models) == 2
    assert captured_models[0] is captured_models[1]  # cached
    assert captured_models[0].__class__.__name__ == "ChatOpenAI"
    assert h._model is captured_models[0]


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


def test_planner_run_rejects_empty_string_env_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "gemma-4-9b-it")
    h = DeepAgentsHarness(
        skills_root=tmp_path / "skills",
        checkpoints_dir=tmp_path / "ck",
        model=None,
        agent_factory=_stub_factory({"messages": []}),
    )
    with pytest.raises(RuntimeError, match="empty env var"):
        h.planner_run(_brief())


def test_planner_run_rejects_non_http_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "file:///etc/passwd")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "gemma-4-9b-it")
    h = DeepAgentsHarness(
        skills_root=tmp_path / "skills",
        checkpoints_dir=tmp_path / "ck",
        model=None,
        agent_factory=_stub_factory({"messages": []}),
    )
    with pytest.raises(RuntimeError, match="http\\(s\\) URL"):
        h.planner_run(_brief())


# -----------------------------------------------------------------------------
# spawn_subagent — v2 stub contract: validate, record, then raise loudly
# -----------------------------------------------------------------------------


def test_spawn_subagent_refuses_before_planner_run(tmp_path: Path) -> None:
    _write_skill(tmp_path / "skills", "find-money-flow")
    h = _harness(tmp_path)

    task = SubagentTask(
        skill_id="find-money-flow@v1",
        inputs={},
        parent_brief_hash=_BRIEF_HASH,
    )
    with pytest.raises(RuntimeError, match="before planner_run"):
        h.spawn_subagent(task)


def test_spawn_subagent_rejects_brief_hash_mismatch(tmp_path: Path) -> None:
    _write_skill(tmp_path / "skills", "find-money-flow")
    brief = _brief()
    h, _ = _harness_with_brief(tmp_path, brief)

    task = SubagentTask(
        skill_id="find-money-flow@v1",
        inputs={},
        parent_brief_hash=_OTHER_HASH,  # not the planner's brief
    )
    with pytest.raises(ValueError, match="cross-investigation dispatch refused"):
        h.spawn_subagent(task)
    # Mismatched dispatches must NOT enter the audit log.
    assert h._state.dispatched_skill_ids == []


def test_spawn_subagent_records_dispatch_then_raises_v2_stub(tmp_path: Path) -> None:
    """Per CLAUDE.md: no silent loss. v2 records the dispatch in audit state, then raises."""
    _write_skill(tmp_path / "skills", "find-money-flow")
    brief = _brief()
    h, _ = _harness_with_brief(tmp_path, brief)

    task = SubagentTask(
        skill_id="find-money-flow@v1",
        inputs={"starting_account": "BE12 1234"},
        parent_brief_hash=brief.compute_hash(),
    )
    with pytest.raises(NotImplementedError, match="v2"):
        h.spawn_subagent(task)

    # State mutation happened BEFORE the raise — auditor can see the attempted dispatch.
    assert h._state.dispatched_skill_ids == ["find-money-flow@v1"]
    assert "find-money-flow@v1" in h._state.loaded_skill_shas


def test_spawn_subagent_records_dispatch_order_under_v2_stub(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "find-money-flow")
    second = _VALID_SKILL_MD.replace("name: find-money-flow", "name: detect-collusion")
    _write_skill(skills_root, "detect-collusion", body=second)

    brief = _brief()
    h, _ = _harness_with_brief(tmp_path, brief)
    bh = brief.compute_hash()

    for sid in ("detect-collusion@v1", "find-money-flow@v1", "detect-collusion@v1"):
        with pytest.raises(NotImplementedError):
            h.spawn_subagent(
                SubagentTask(skill_id=sid, inputs={}, parent_brief_hash=bh)
            )

    assert h._state.dispatched_skill_ids == [
        "detect-collusion@v1",
        "find-money-flow@v1",
        "detect-collusion@v1",
    ]


# -----------------------------------------------------------------------------
# checkpoint / resume
# -----------------------------------------------------------------------------


def test_checkpoint_round_trip_restores_state(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, "find-money-flow")

    brief = _brief()
    factory = _stub_factory({"messages": [{"role": "user", "content": "x"}]})
    h = _harness(tmp_path, factory=factory)
    h.planner_run(brief)
    with pytest.raises(NotImplementedError):
        h.spawn_subagent(
            SubagentTask(
                skill_id="find-money-flow@v1",
                inputs={},
                parent_brief_hash=brief.compute_hash(),
            )
        )
    cid = h.checkpoint()

    # Fresh harness -> resume -> state recovered byte-for-byte.
    h2 = _harness(tmp_path, factory=_stub_factory({"messages": []}))
    h2.resume(cid)

    assert h2._state.skill_load_log == ["find-money-flow@v1"]
    assert h2._state.dispatched_skill_ids == ["find-money-flow@v1"]
    assert h2._state.plan_log == ["user"]
    assert h2._state.last_brief_hash == brief.compute_hash()
    assert "find-money-flow@v1" in h2._state.loaded_skill_shas


def test_checkpoint_id_is_content_addressable(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    h._state = _HarnessState(
        skill_load_log=["a@v1", "b@v2"],
        loaded_skill_shas={"a@v1": "0" * 40, "b@v2": "1" * 40},
    )
    cid = h.checkpoint()

    payload = (tmp_path / "ck" / f"{cid}.json").read_text()
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == cid

    parsed = json.loads(payload)
    assert parsed["skill_load_log"] == ["a@v1", "b@v2"]
    assert parsed["loaded_skill_shas"] == {"a@v1": "0" * 40, "b@v2": "1" * 40}


def test_checkpoint_canonical_serialization_is_stable() -> None:
    s = _HarnessState(
        skill_load_log=["a@v1"],
        loaded_skill_shas={"a@v1": "0" * 40},
        dispatched_skill_ids=["a@v1", "b@v1"],
        plan_log=["user", "ai", "tool"],
        last_brief_hash=_BRIEF_HASH,
    )
    expected = (
        '{"dispatched_skill_ids":["a@v1","b@v1"],'
        f'"last_brief_hash":"{_BRIEF_HASH}",'
        '"loaded_skill_shas":{"a@v1":"' + ("0" * 40) + '"},'
        '"plan_log":["user","ai","tool"],'
        '"skill_load_log":["a@v1"]}'
    )
    assert s.to_canonical_json() == expected
    assert _HarnessState.from_canonical_json(expected).to_canonical_json() == expected


def test_checkpoint_atomic_write_leaves_no_partial_file(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    h._state = _HarnessState(skill_load_log=["x@v1"], loaded_skill_shas={"x@v1": "0" * 40})
    cid = h.checkpoint()

    files = list((tmp_path / "ck").iterdir())
    assert files == [tmp_path / "ck" / f"{cid}.json"]  # no .tmp residue


def test_resume_unknown_checkpoint_raises_filenotfound(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    with pytest.raises(FileNotFoundError):
        h.resume(CheckpointId("0" * 64))


def test_resume_rejects_malformed_checkpoint_id(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    with pytest.raises(ValueError, match="64 lowercase hex"):
        h.resume(CheckpointId("../etc/passwd"))
    with pytest.raises(ValueError, match="64 lowercase hex"):
        h.resume(CheckpointId("Z" * 64))


def test_resume_rejects_tampered_checkpoint(tmp_path: Path) -> None:
    """File contents must hash back to the filename."""
    h = _harness(tmp_path)
    h._state = _HarnessState(skill_load_log=["x@v1"], loaded_skill_shas={"x@v1": "0" * 40})
    cid = h.checkpoint()

    # Tamper: rewrite the file under the same name with different (but valid) JSON.
    tampered = _HarnessState(skill_load_log=["other@v1"], loaded_skill_shas={"other@v1": "1" * 40})
    (tmp_path / "ck" / f"{cid}.json").write_text(
        tampered.to_canonical_json(), encoding="utf-8"
    )

    h2 = _harness(tmp_path)
    with pytest.raises(CheckpointIntegrityError, match="integrity check"):
        h2.resume(cid)


def test_resume_rejects_malformed_payload_via_pydantic(tmp_path: Path) -> None:
    """Pydantic extra=forbid + per-field types reject the original silent-corruption bug.

    The pre-fix code did `list(obj["skill_load_log"])` which silently turned
    the string "find-money-flow@v1" into ["f","i","n","d",...]. Pydantic
    catches this as a type error.
    """
    bogus_payload = json.dumps(
        {
            "skill_load_log": "find-money-flow@v1",  # string, should be list
            "loaded_skill_shas": {},
            "dispatched_skill_ids": [],
            "plan_log": [],
            "last_brief_hash": None,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    cid = hashlib.sha256(bogus_payload.encode("utf-8")).hexdigest()
    ck_dir = tmp_path / "ck"
    ck_dir.mkdir(parents=True)
    (ck_dir / f"{cid}.json").write_text(bogus_payload, encoding="utf-8")

    h = _harness(tmp_path)
    with pytest.raises(ValidationError):
        h.resume(CheckpointId(cid))


def test_resume_rejects_unknown_fields(tmp_path: Path) -> None:
    """extra=forbid: a future-format checkpoint with an unknown key fails loud."""
    payload = json.dumps(
        {
            "skill_load_log": [],
            "loaded_skill_shas": {},
            "dispatched_skill_ids": [],
            "plan_log": [],
            "last_brief_hash": None,
            "rogue_field": "smuggled",
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    cid = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    ck_dir = tmp_path / "ck"
    ck_dir.mkdir(parents=True)
    (ck_dir / f"{cid}.json").write_text(payload, encoding="utf-8")

    h = _harness(tmp_path)
    with pytest.raises(ValidationError):
        h.resume(CheckpointId(cid))


# -----------------------------------------------------------------------------
# _extract_plan_log / _extract_notes
# -----------------------------------------------------------------------------


def test_extract_plan_log_handles_basemessage_style_attr() -> None:
    msg = SimpleNamespace(type="ai", content="hello")
    assert _extract_plan_log({"messages": [msg]}) == ("ai",)


def test_extract_plan_log_dict_with_neither_role_nor_type_yields_unknown() -> None:
    assert _extract_plan_log({"messages": [{"content": "x"}]}) == ("unknown",)


def test_extract_plan_log_non_mapping_returns_empty() -> None:
    assert _extract_plan_log("not a mapping") == ()  # type: ignore[arg-type]
    assert _extract_plan_log({}) == ()


def test_extract_notes_returns_empty_when_no_notes_key() -> None:
    assert _extract_notes({"messages": []}) == ()


def test_extract_notes_raises_on_non_list_notes() -> None:
    with pytest.raises(TypeError, match="must be a list"):
        _extract_notes({"notes": "not a list"})


def test_extract_notes_validates_each_note_via_pydantic() -> None:
    # A malformed Note dict (missing required field) must surface as a ValidationError,
    # not be silently skipped.
    with pytest.raises(ValidationError):
        _extract_notes({"notes": [{"claim": "incomplete"}]})


# -----------------------------------------------------------------------------
# git_blob_sha1
# -----------------------------------------------------------------------------


def test_git_blob_sha1_matches_git_hash_object() -> None:
    # `git hash-object` of the empty blob is a well-known constant.
    assert _git_blob_sha1(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    # And of "hello\n".
    assert _git_blob_sha1(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"
