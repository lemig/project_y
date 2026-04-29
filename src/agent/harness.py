"""AgentHarness — stable interface around the agent runtime.

The v2 concrete adapter wraps Deep Agents (LangChain, Apache 2.0) at a pinned
version. Skills, audit code, and tests depend on this interface, not on Deep
Agents directly. Any harness or runtime upgrade triggers golden-run replay
tests; if output drifts, CI fails.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from types import MappingProxyType
from typing import Any, NewType

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schema.brief import Brief
from schema.note import Note
from skills.skill import Skill

CheckpointId = NewType("CheckpointId", str)

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA1_HEX_RE = re.compile(r"^[0-9a-f]{40}$")


def _deep_freeze(obj: Any) -> Any:
    """Recursively wrap dicts in MappingProxyType and lists/sets in tuples/frozensets.

    Pydantic's frozen=True only blocks attribute assignment on the instance —
    it does not deep-freeze nested containers. SubagentTask.inputs is the
    replay-determinism boundary, so we freeze its contents at validation time
    to prevent post-construction mutation from corrupting checkpoints.
    """
    if isinstance(obj, dict):
        return MappingProxyType({k: _deep_freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(_deep_freeze(v) for v in obj)
    if isinstance(obj, (set, frozenset)):
        return frozenset(_deep_freeze(v) for v in obj)
    return obj


class SubagentTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    skill_id: str = Field(min_length=1)
    inputs: dict[str, Any]
    parent_brief_hash: str

    @field_validator("parent_brief_hash")
    @classmethod
    def _v_sha(cls, v: str) -> str:
        if not _SHA256_HEX_RE.match(v):
            raise ValueError("parent_brief_hash must be 64 lowercase hex chars (sha256)")
        return v

    @model_validator(mode="after")
    def _freeze_inputs(self) -> "SubagentTask":
        # frozen=True blocks attribute assignment; object.__setattr__ bypasses
        # that to install the deep-frozen view.
        object.__setattr__(self, "inputs", _deep_freeze(self.inputs))
        return self


class SubagentResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    notes: tuple[Note, ...]
    skill_id: str = Field(min_length=1)
    skill_version: str

    @field_validator("skill_version")
    @classmethod
    def _v_git_sha(cls, v: str) -> str:
        if not _GIT_SHA1_HEX_RE.match(v):
            raise ValueError("skill_version must be a 40-char lowercase hex git SHA-1")
        return v


class PlannerResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    notes: tuple[Note, ...]
    plan_log: tuple[str, ...]


class AgentHarness(ABC):
    """Stable interface over the agent runtime. v2 wraps Deep Agents."""

    @abstractmethod
    def planner_run(self, brief: Brief) -> PlannerResult:
        """Run the top-level planner for a brief and return grounded notes."""

    @abstractmethod
    def spawn_subagent(self, task: SubagentTask) -> SubagentResult:
        """Delegate a sub-task to a skill-bound subagent."""

    @abstractmethod
    def load_skill(self, skill_id: str) -> Skill:
        """Resolve `name@version` to a parsed Skill, pinned to its git_sha at load time."""

    @abstractmethod
    def checkpoint(self) -> CheckpointId:
        """Persist the current planner+subagent state. Returns an opaque id."""

    @abstractmethod
    def resume(self, checkpoint_id: CheckpointId) -> None:
        """Restore state from a previously-recorded checkpoint."""
