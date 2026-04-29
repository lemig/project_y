"""AgentHarness interface contract.

Pure-interface tests. The Deep Agents adapter has its own integration tests.
"""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from agent.harness import (
    AgentHarness,
    CheckpointId,
    PlannerResult,
    SubagentResult,
    SubagentTask,
)
from schema.brief import Brief
from skills.skill import Skill, SkillFrontmatter

_GOOD_HASH = "a" * 64
_GIT_SHA = hashlib.sha1(b"skill-v1").hexdigest()  # 40-char hex


def _brief() -> Brief:
    return Brief(text="Trace the 120k from contract X.", corpus_snapshot_hash=_GOOD_HASH)


def test_abstract_harness_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        AgentHarness()  # type: ignore[abstract]


class _FakeHarness(AgentHarness):
    def __init__(self) -> None:
        self._checkpoints: dict[str, str] = {}

    def planner_run(self, brief: Brief) -> PlannerResult:
        return PlannerResult(notes=(), plan_log=(f"planned for: {brief.text}",))

    def spawn_subagent(self, task: SubagentTask) -> SubagentResult:
        return SubagentResult(notes=(), skill_id=task.skill_id, skill_version=_GIT_SHA)

    def load_skill(self, skill_id: str) -> Skill:
        name, version = skill_id.split("@")
        return Skill(
            frontmatter=SkillFrontmatter(
                name=name,
                version=version,
                owner="m.cabero@olaf.eu",
                resolver=r"money|flow",
                output_schema_ref="schema.note.Note",
                verifier="verifier.substring_quote",
                tests_dir=f"tests/skills/{name}",
            ),
            body=f"# {name}\n\nMethodology body.",
            git_sha=_GIT_SHA,
        )

    def checkpoint(self) -> CheckpointId:
        cid = CheckpointId(f"ck-{len(self._checkpoints) + 1}")
        self._checkpoints[cid] = "state-snapshot"
        return cid

    def resume(self, checkpoint_id: CheckpointId) -> None:
        if checkpoint_id not in self._checkpoints:
            raise KeyError(checkpoint_id)


def test_fake_harness_implements_all_methods() -> None:
    h = _FakeHarness()

    pr = h.planner_run(_brief())
    assert isinstance(pr, PlannerResult)
    assert pr.plan_log[0].startswith("planned for: ")

    sr = h.spawn_subagent(
        SubagentTask(
            skill_id="find-money-flow@v1",
            inputs={"starting_account": "BE12 1234"},
            parent_brief_hash=_GOOD_HASH,
        )
    )
    assert isinstance(sr, SubagentResult)
    assert sr.skill_id == "find-money-flow@v1"

    skill = h.load_skill("find-money-flow@v1")
    assert skill.skill_id == "find-money-flow@v1"
    assert skill.frontmatter.name == "find-money-flow"

    cid = h.checkpoint()
    h.resume(cid)


def test_subagent_task_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        SubagentTask(
            skill_id="x@v1",
            inputs={},
            parent_brief_hash=_GOOD_HASH,
            extra="nope",  # type: ignore[call-arg]
        )


def test_subagent_task_inputs_freeform_read_access() -> None:
    t = SubagentTask(
        skill_id="x@v1",
        inputs={"nested": {"list": [1, 2, 3]}, "n": 42, "s": "hi"},
        parent_brief_hash=_GOOD_HASH,
    )
    assert t.inputs["n"] == 42
    assert t.inputs["s"] == "hi"
    assert t.inputs["nested"]["list"] == (1, 2, 3)  # list deep-frozen to tuple


def test_subagent_task_inputs_top_level_immutable() -> None:
    t = SubagentTask(
        skill_id="x@v1",
        inputs={"a": 1},
        parent_brief_hash=_GOOD_HASH,
    )
    with pytest.raises(TypeError):
        t.inputs["a"] = 999  # MappingProxyType blocks assignment


def test_subagent_task_inputs_nested_dict_immutable() -> None:
    t = SubagentTask(
        skill_id="x@v1",
        inputs={"nested": {"k": "v"}},
        parent_brief_hash=_GOOD_HASH,
    )
    with pytest.raises(TypeError):
        t.inputs["nested"]["k"] = "tampered"


def test_subagent_task_inputs_dict_inside_tuple_immutable() -> None:
    # codex: tuples were originally not deep-frozen; nested dicts inside tuples
    # remained aliased + mutable. Verify recursion now reaches them.
    t = SubagentTask(
        skill_id="x@v1",
        inputs={"x": ({"k": "v"},)},
        parent_brief_hash=_GOOD_HASH,
    )
    inner = t.inputs["x"][0]
    with pytest.raises(TypeError):
        inner["k"] = "tampered"


def test_subagent_task_inputs_dict_inside_caller_tuple_decoupled() -> None:
    inner_dict: dict[str, object] = {"k": "original"}
    caller_tuple = (inner_dict,)
    t = SubagentTask(
        skill_id="x@v1",
        inputs={"x": caller_tuple},
        parent_brief_hash=_GOOD_HASH,
    )
    inner_dict["k"] = "tampered"
    assert t.inputs["x"][0]["k"] == "original"


def test_subagent_task_inputs_decoupled_from_caller_dict() -> None:
    # Mutating the caller's dict after construction must not affect the task.
    caller_dict: dict[str, object] = {"k": "original"}
    t = SubagentTask(
        skill_id="x@v1",
        inputs=caller_dict,
        parent_brief_hash=_GOOD_HASH,
    )
    caller_dict["k"] = "tampered"
    assert t.inputs["k"] == "original"


def test_subagent_task_parent_brief_hash_validated() -> None:
    with pytest.raises(ValidationError):
        SubagentTask(skill_id="x@v1", inputs={}, parent_brief_hash="not-a-sha")
    with pytest.raises(ValidationError):
        SubagentTask(skill_id="x@v1", inputs={}, parent_brief_hash="A" * 64)  # uppercase
    with pytest.raises(ValidationError):
        SubagentTask(skill_id="x@v1", inputs={}, parent_brief_hash="a" * 63)  # short


def test_subagent_result_skill_version_must_be_40_hex() -> None:
    with pytest.raises(ValidationError):
        SubagentResult(notes=(), skill_id="x@v1", skill_version="abc1234")
    with pytest.raises(ValidationError):
        SubagentResult(notes=(), skill_id="x@v1", skill_version="A" * 40)


def test_planner_result_frozen() -> None:
    pr = PlannerResult(notes=(), plan_log=("a", "b"))
    with pytest.raises(ValidationError):
        pr.plan_log = ("c",)  # type: ignore[misc]


def test_skill_id_property() -> None:
    s = Skill(
        frontmatter=SkillFrontmatter(
            name="foo",
            version="v2",
            owner="x",
            resolver="r",
            output_schema_ref="r",
            verifier="r",
            tests_dir="r",
        ),
        body="",
        git_sha=_GIT_SHA,
    )
    assert s.skill_id == "foo@v2"


def test_skill_git_sha_must_be_40_hex() -> None:
    fm = SkillFrontmatter(
        name="foo",
        version="v2",
        owner="x",
        resolver="r",
        output_schema_ref="r",
        verifier="r",
        tests_dir="r",
    )
    with pytest.raises(ValidationError):
        Skill(frontmatter=fm, body="", git_sha="abc1234")
    with pytest.raises(ValidationError):
        Skill(frontmatter=fm, body="", git_sha="deadbeefcafebabe")  # 16 chars
    with pytest.raises(ValidationError):
        Skill(frontmatter=fm, body="", git_sha="A" * 40)  # uppercase
