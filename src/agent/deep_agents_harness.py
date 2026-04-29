"""DeepAgentsHarness — concrete adapter wrapping LangChain Deep Agents (MIT).

Wraps the pinned `deepagents==0.4.12` runtime behind the `AgentHarness` ABC.
The harness itself is deterministic Python; the only non-deterministic
component is the underlying LLM, which is endpoint-configurable via env vars
(`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`). The same code targets the
OpenRouter/Vertex dev endpoint and the air-gapped vLLM prod endpoint — only
the URL changes.

`planner_run` passes `brief.text` as the sole user message and intentionally
sets no `system_prompt` on the underlying deep-agent — skill bodies will
supply per-task framing once skills are wired in v3.

Per CLAUDE.md, every dep upgrade must trigger golden-run replay tests; if
any deterministic output (skill load order, dispatched skill_ids, checkpoint
contents) drifts, CI fails.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

import yaml
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA1_HEX_RE = re.compile(r"^[0-9a-f]{40}$")
_FRONTMATTER_OPEN = "---\n"
_FRONTMATTER_CLOSE = "\n---\n"
_SKILL_MANIFEST_FILENAME = "SKILL.md"
_DEFAULT_SKILLS_ROOT = Path("skills")
_DEFAULT_CHECKPOINTS_DIR = Path("data/checkpoints")
_SKILL_MAX_BYTES = 1 << 20  # 1 MiB; defends against runaway/hostile manifests.


class CheckpointIntegrityError(ValueError):
    """A checkpoint file failed sha256 hash verification on resume.

    Specific subclass of ValueError so callers can catch integrity failures
    distinct from the generic schema-validation errors Pydantic raises on
    malformed payloads. Per CLAUDE.md (no `except Exception:`), audit-trail
    errors must be catchable by class.
    """


def _git_blob_sha1(content: bytes) -> str:
    """Compute git's SHA-1 blob hash of `content` — matches `git hash-object`.

    Pure deterministic Python: no shell, no git binary, no working tree.
    Identical bytes → identical SHA on every machine, which is what
    `Skill.git_sha` is contracted to be.

    Note: SHA-1 here is contractual (git-blob format compatibility), not a
    security primitive — collision resistance is not relied on. The
    audit-trail integrity claim sits on the SHA-256 checkpoint id and the
    substring quote verifier (separate workspace).
    """
    header = f"blob {len(content)}\x00".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split a SKILL.md into (frontmatter, body). Tolerant of CRLF and BOM.

    BOM is stripped by the caller via `utf-8-sig` decode; we additionally
    normalize CRLF→LF so files committed through `core.autocrlf=true` (or
    edited on Windows) parse identically to LF-only files. Same bytes →
    same git_sha pin is the contract callers rely on.
    """
    text = text.replace("\r\n", "\n")
    if not text.startswith(_FRONTMATTER_OPEN):
        raise ValueError(
            f"{_SKILL_MANIFEST_FILENAME} must start with a '---' YAML frontmatter block"
        )
    end = text.find(_FRONTMATTER_CLOSE, len(_FRONTMATTER_OPEN))
    if end < 0:
        raise ValueError(
            f"{_SKILL_MANIFEST_FILENAME} frontmatter has no closing '---' delimiter"
        )
    front = text[len(_FRONTMATTER_OPEN) : end]
    body = text[end + len(_FRONTMATTER_CLOSE) :]
    return front, body


def _parse_frontmatter(front_text: str) -> SkillFrontmatter:
    parsed = yaml.safe_load(front_text)
    if not isinstance(parsed, dict):
        raise ValueError(
            f"{_SKILL_MANIFEST_FILENAME} frontmatter must be a YAML mapping"
        )
    return SkillFrontmatter(**parsed)


class _HarnessState(BaseModel):
    """Persistable, deterministic harness state. No LLM token streams.

    Pydantic with `extra="forbid"` + per-field type validation rejects
    malformed checkpoint payloads on resume — coercing a stringified
    `skill_load_log` into a character list (the original bug) is no longer
    possible. Field set is locked; any change is a checkpoint-format bump
    and needs a golden regen.

    `loaded_skill_shas` pins each loaded skill's git_sha into the audit
    state so a paused investigation cannot silently continue under
    different methodology bytes after a SKILL.md edit (court-defensibility
    contract per CLAUDE.md).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    skill_load_log: list[str] = Field(default_factory=list)
    loaded_skill_shas: dict[str, str] = Field(default_factory=dict)
    dispatched_skill_ids: list[str] = Field(default_factory=list)
    plan_log: list[str] = Field(default_factory=list)
    last_brief_hash: str | None = None

    @field_validator("loaded_skill_shas")
    @classmethod
    def _v_skill_shas(cls, v: dict[str, str]) -> dict[str, str]:
        for skill_id, sha in v.items():
            if not _GIT_SHA1_HEX_RE.match(sha):
                raise ValueError(
                    f"loaded_skill_shas[{skill_id!r}] must be a 40-char "
                    "lowercase hex git SHA-1"
                )
        return v

    @field_validator("last_brief_hash")
    @classmethod
    def _v_last_brief_hash(cls, v: str | None) -> str | None:
        if v is not None and not _SHA256_HEX_RE.match(v):
            raise ValueError(
                "last_brief_hash must be 64 lowercase hex chars (sha256)"
            )
        return v

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="python"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def from_canonical_json(cls, payload: str) -> "_HarnessState":
        return cls.model_validate_json(payload)


def _build_chat_model_from_env() -> BaseChatModel:
    """Build a `ChatOpenAI` against the OpenAI-compatible endpoint named in env.

    The dev/prod swap (OpenRouter → vLLM) is purely an env-var change per
    CLAUDE.md's dev-environment section. `temperature=0` is the v2 default
    so unit tests' golden runs aren't held hostage by sampler noise.
    Empty-string env vars (a common `.env` foot-gun) are rejected up front
    so misconfigurations fail loud rather than emerging as confusing httpx
    errors deep inside langchain.
    """
    required = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")
    missing = [k for k in required if not os.environ.get(k, "").strip()]
    if missing:
        raise RuntimeError(
            f"Missing or empty env var(s) {missing}: set LLM_BASE_URL, "
            "LLM_API_KEY, LLM_MODEL (any OpenAI-compatible endpoint)"
        )
    base_url = os.environ["LLM_BASE_URL"].strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RuntimeError(
            f"LLM_BASE_URL must be an http(s) URL with a host; got {base_url!r}"
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=base_url,
        api_key=os.environ["LLM_API_KEY"].strip(),
        model=os.environ["LLM_MODEL"].strip(),
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
            env vars on first `planner_run` and cached on `self._model`.
        agent_factory: Override for `deepagents.create_deep_agent`. Tests
            inject a stub compiled-graph factory so they don't depend on a
            real LLM.

    v2 contract notes:
    - `spawn_subagent` is a v2 stub: it validates the dispatch (parent brief
      hash match, skill SHA pin) and records the dispatch in audit state,
      then raises `NotImplementedError`. Skill execution is wired in v3
      once skills land. Returning a fake-success `SubagentResult(notes=())`
      would be silent data loss — explicitly disallowed by CLAUDE.md.
    - `planner_run` invokes `create_deep_agent` with no `system_prompt`;
      `brief.text` is the sole user message. Skill bodies will supply
      per-task framing on dispatch in v3.
    """

    def __init__(
        self,
        skills_root: Path | str = _DEFAULT_SKILLS_ROOT,
        checkpoints_dir: Path | str = _DEFAULT_CHECKPOINTS_DIR,
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

    def planner_run(self, brief: Brief) -> PlannerResult:
        if self._model is None:
            self._model = _build_chat_model_from_env()
        agent = self._agent_factory(model=self._model, tools=[])
        result = agent.invoke({"messages": [{"role": "user", "content": brief.text}]})
        notes = _extract_notes(result)
        plan_log = _extract_plan_log(result)
        self._state.last_brief_hash = brief.compute_hash()
        self._state.plan_log = list(plan_log)
        return PlannerResult(notes=notes, plan_log=plan_log)

    def spawn_subagent(self, task: SubagentTask) -> SubagentResult:
        if self._state.last_brief_hash is None:
            raise RuntimeError(
                "spawn_subagent called before planner_run; no brief in scope "
                "to validate task.parent_brief_hash against"
            )
        if task.parent_brief_hash != self._state.last_brief_hash:
            raise ValueError(
                f"task.parent_brief_hash {task.parent_brief_hash!r} does not "
                f"match the harness's current brief hash "
                f"{self._state.last_brief_hash!r} — cross-investigation "
                "dispatch refused"
            )
        skill = self.load_skill(task.skill_id)
        self._state.dispatched_skill_ids.append(task.skill_id)
        # v2 contract: dispatch is recorded in audit state, then we refuse
        # loudly. Returning SubagentResult(notes=()) here would be silent
        # data loss — every "skill ran, found nothing" would be
        # indistinguishable from "skill never ran." CLAUDE.md is explicit:
        # "No silent loss in the audit log."
        raise NotImplementedError(
            f"spawn_subagent: skill execution not wired in v2 (skill "
            f"{skill.skill_id} pinned at git_sha={skill.git_sha}, dispatch "
            "recorded in audit state). Awaits the skills workspace."
        )

    def load_skill(self, skill_id: str) -> Skill:
        m = _SKILL_ID_RE.match(skill_id)
        if not m:
            raise ValueError(
                f"skill_id must match '<name>@<version>': got {skill_id!r}"
            )
        name = m.group("name")
        version = m.group("version")
        path = self._skills_root / name / _SKILL_MANIFEST_FILENAME
        if not path.is_file():
            raise FileNotFoundError(f"skill file not found: {path}")
        size = path.stat().st_size
        if size > _SKILL_MAX_BYTES:
            raise ValueError(
                f"skill file {path} exceeds size cap "
                f"({size} > {_SKILL_MAX_BYTES} bytes)"
            )
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")  # tolerates a leading UTF-8 BOM
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
        git_sha = _git_blob_sha1(raw)
        pinned = self._state.loaded_skill_shas.get(skill_id)
        if pinned is not None and pinned != git_sha:
            raise ValueError(
                f"skill {skill_id} drift: pinned git_sha={pinned} but disk "
                f"now hashes to {git_sha}. A SKILL.md edit during a live "
                "investigation breaks replay determinism; refusing to load."
            )
        skill = Skill(frontmatter=frontmatter, body=body, git_sha=git_sha)
        if pinned is None:
            self._state.loaded_skill_shas[skill_id] = git_sha
            self._state.skill_load_log.append(skill_id)
        return skill

    def checkpoint(self) -> CheckpointId:
        self._checkpoints_dir.mkdir(parents=True, exist_ok=True)
        payload = self._state.to_canonical_json()
        cid = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        final = self._checkpoints_dir / f"{cid}.json"
        # Atomic write: temp + os.replace. `os.replace` is atomic on POSIX
        # and on Windows (when src and dst are on the same filesystem),
        # which is the case here since both live under self._checkpoints_dir.
        # Without this, a crash or ENOSPC mid-write would leave a truncated
        # file under a content-addressed name and resume() would deserialize
        # corrupt state — exactly what the sha256 verify on resume guards
        # against, but the atomic write makes the failure mode explicit.
        tmp = self._checkpoints_dir / f"{cid}.{secrets.token_hex(8)}.tmp"
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, final)
        return CheckpointId(cid)

    def resume(self, checkpoint_id: CheckpointId) -> None:
        if not _SHA256_HEX_RE.match(checkpoint_id):
            raise ValueError(
                f"checkpoint_id must be 64 lowercase hex chars (sha256): "
                f"got {checkpoint_id!r}"
            )
        path = self._checkpoints_dir / f"{checkpoint_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"checkpoint not found: {path}")
        payload = path.read_text(encoding="utf-8")
        observed = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if observed != checkpoint_id:
            raise CheckpointIntegrityError(
                f"checkpoint {checkpoint_id} failed integrity check: file "
                f"contents hash to {observed}. Possible tampering, corruption, "
                "or partial write."
            )
        self._state = _HarnessState.from_canonical_json(payload)
