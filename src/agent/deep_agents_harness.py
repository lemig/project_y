"""DeepAgentsHarness — concrete adapter wrapping LangChain Deep Agents (MIT).

Wraps the pinned `deepagents==0.4.12` runtime behind the `AgentHarness` ABC.
The harness itself is deterministic Python; the only non-deterministic
component is the underlying LLM, which is endpoint-configurable via env vars
(`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`). The same code targets the
OpenRouter/Vertex dev endpoint and the air-gapped vLLM prod endpoint — only
the URL changes.

Per CLAUDE.md, every dep upgrade must trigger golden-run replay tests; if
any deterministic output (skill load order, dispatched skill_ids, checkpoint
contents) drifts, CI fails.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml
from langchain_core.language_models import BaseChatModel

from agent.harness import (
    AgentHarness,
    CheckpointId,
    PlannerResult,
    SubagentResult,
    SubagentTask,
)
from schema.brief import Brief
from schema.note import Note
from skills.skill import Skill, SkillFrontmatter

_SKILL_ID_RE = re.compile(r"^(?P<name>[a-z0-9][a-z0-9_\-]*)@(?P<version>[a-zA-Z0-9_.\-]+)$")
_FRONTMATTER_OPEN = "---\n"
_FRONTMATTER_CLOSE = "\n---\n"


def _git_blob_sha1(content: bytes) -> str:
    """Compute git's SHA-1 blob hash of `content` — matches `git hash-object`.

    Pure deterministic Python: no shell, no git binary, no working tree.
    Identical bytes → identical SHA on every machine, which is what
    `Skill.git_sha` is contracted to be.
    """
    header = f"blob {len(content)}\x00".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith(_FRONTMATTER_OPEN):
        raise ValueError("SKILL.md must start with a '---' YAML frontmatter block")
    end = text.find(_FRONTMATTER_CLOSE, len(_FRONTMATTER_OPEN))
    if end < 0:
        raise ValueError("SKILL.md frontmatter has no closing '---' delimiter")
    front = text[len(_FRONTMATTER_OPEN) : end]
    body = text[end + len(_FRONTMATTER_CLOSE) :]
    return front, body


def _parse_frontmatter(front_text: str) -> SkillFrontmatter:
    parsed = yaml.safe_load(front_text)
    if not isinstance(parsed, dict):
        raise ValueError("SKILL.md frontmatter must be a YAML mapping")
    return SkillFrontmatter(**parsed)


@dataclass
class _HarnessState:
    """Persistable, deterministic harness state. No LLM token streams.

    The fields here are exactly what the golden-run replay test asserts
    against. Keep this lean and stable; any change is a checkpoint-format
    bump and needs a golden regen.
    """

    skill_load_log: list[str] = field(default_factory=list)
    dispatched_skill_ids: list[str] = field(default_factory=list)
    plan_log: list[str] = field(default_factory=list)
    last_brief_hash: str | None = None

    def to_canonical_json(self) -> str:
        return json.dumps(
            {
                "skill_load_log": list(self.skill_load_log),
                "dispatched_skill_ids": list(self.dispatched_skill_ids),
                "plan_log": list(self.plan_log),
                "last_brief_hash": self.last_brief_hash,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def from_canonical_json(cls, payload: str) -> "_HarnessState":
        obj = json.loads(payload)
        return cls(
            skill_load_log=list(obj["skill_load_log"]),
            dispatched_skill_ids=list(obj["dispatched_skill_ids"]),
            plan_log=list(obj["plan_log"]),
            last_brief_hash=obj["last_brief_hash"],
        )


def _build_chat_model_from_env() -> BaseChatModel:
    """Build a `ChatOpenAI` against the OpenAI-compatible endpoint named in env.

    The dev/prod swap (OpenRouter → vLLM) is purely an env-var change per
    CLAUDE.md's dev-environment section. `temperature=0` is the v2 default
    so unit tests' golden runs aren't held hostage by sampler noise.
    """
    missing = [k for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL") if k not in os.environ]
    if missing:
        raise RuntimeError(
            f"Missing required env var(s) {missing}: set LLM_BASE_URL, "
            "LLM_API_KEY, LLM_MODEL (any OpenAI-compatible endpoint)"
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        model=os.environ["LLM_MODEL"],
        temperature=0,
    )


def _extract_plan_log(result: Mapping[str, Any]) -> tuple[str, ...]:
    """Distill the agent's message trace into role labels for the audit log.

    Token-level content is non-deterministic and not safe to store in the
    audit trail. The role sequence (`human`, `ai`, `tool`, ...) is the
    structurally-deterministic part — useful for replay diffs and stable
    enough to gate dep upgrades against.
    """
    msgs = result.get("messages") if isinstance(result, Mapping) else None
    out: list[str] = []
    if msgs is None:
        return tuple(out)
    for m in msgs:
        role = getattr(m, "type", None)
        if role is None and isinstance(m, dict):
            role = m.get("role") or m.get("type")
        out.append(role if isinstance(role, str) and role else "unknown")
    return tuple(out)


def _extract_notes(result: Mapping[str, Any]) -> tuple[Note, ...]:
    raw = result.get("notes") if isinstance(result, Mapping) else None
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise TypeError(f"agent state 'notes' must be a list, got {type(raw).__name__}")
    return tuple(Note.model_validate(item) for item in raw)


class DeepAgentsHarness(AgentHarness):
    """Concrete `AgentHarness` over Deep Agents.

    Args:
        skills_root: Filesystem root holding `<name>/SKILL.md` for each skill.
        checkpoints_dir: Directory under which checkpoint JSON files are
            written; created on first checkpoint.
        model: A pre-built langchain `BaseChatModel`. If `None`, one is
            constructed from the `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`
            env vars on first `planner_run`.
        agent_factory: Override for `deepagents.create_deep_agent`. Tests
            inject a stub compiled-graph factory so they don't depend on a
            real LLM.
    """

    def __init__(
        self,
        skills_root: Path | str = "skills",
        checkpoints_dir: Path | str = "data/checkpoints",
        model: BaseChatModel | None = None,
        agent_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._skills_root = Path(skills_root)
        self._checkpoints_dir = Path(checkpoints_dir)
        self._model = model
        if agent_factory is None:
            from deepagents import create_deep_agent

            agent_factory = create_deep_agent
        self._agent_factory = agent_factory
        self._state = _HarnessState()
        self._loaded_skills: dict[str, Skill] = {}

    def planner_run(self, brief: Brief) -> PlannerResult:
        model = self._model if self._model is not None else _build_chat_model_from_env()
        agent = self._agent_factory(model=model, tools=[])
        result = agent.invoke({"messages": [{"role": "user", "content": brief.text}]})
        notes = _extract_notes(result)
        plan_log = _extract_plan_log(result)
        self._state.last_brief_hash = brief.compute_hash()
        self._state.plan_log = list(plan_log)
        return PlannerResult(notes=notes, plan_log=plan_log)

    def spawn_subagent(self, task: SubagentTask) -> SubagentResult:
        skill = self.load_skill(task.skill_id)
        self._state.dispatched_skill_ids.append(task.skill_id)
        return SubagentResult(
            notes=(),
            skill_id=task.skill_id,
            skill_version=skill.git_sha,
        )

    def load_skill(self, skill_id: str) -> Skill:
        m = _SKILL_ID_RE.match(skill_id)
        if not m:
            raise ValueError(
                f"skill_id must match '<name>@<version>': got {skill_id!r}"
            )
        name = m.group("name")
        version = m.group("version")
        path = self._skills_root / name / "SKILL.md"
        if not path.is_file():
            raise FileNotFoundError(f"skill file not found: {path}")
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"skill file {path} is not valid UTF-8") from e
        front_text, body = _split_frontmatter(text)
        frontmatter = _parse_frontmatter(front_text)
        if frontmatter.name != name:
            raise ValueError(
                f"skill_id name {name!r} disagrees with frontmatter name "
                f"{frontmatter.name!r} in {path}"
            )
        if frontmatter.version != version:
            raise ValueError(
                f"skill_id version {version!r} disagrees with frontmatter "
                f"version {frontmatter.version!r} in {path}"
            )
        skill = Skill(
            frontmatter=frontmatter,
            body=body,
            git_sha=_git_blob_sha1(raw),
        )
        if skill_id not in self._state.skill_load_log:
            self._state.skill_load_log.append(skill_id)
        self._loaded_skills[skill_id] = skill
        return skill

    def checkpoint(self) -> CheckpointId:
        self._checkpoints_dir.mkdir(parents=True, exist_ok=True)
        payload = self._state.to_canonical_json()
        cid = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        out = self._checkpoints_dir / f"{cid}.json"
        out.write_text(payload, encoding="utf-8")
        return CheckpointId(cid)

    def resume(self, checkpoint_id: CheckpointId) -> None:
        path = self._checkpoints_dir / f"{checkpoint_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"checkpoint not found: {path}")
        payload = path.read_text(encoding="utf-8")
        self._state = _HarnessState.from_canonical_json(payload)
