"""Skill — a parsed SKILL.md file with YAML frontmatter and methodology body.

Skills are markdown documents on disk. The frontmatter pins the contract
(name, version, owner, resolver, output_schema_ref, verifier, tests_dir)
that the harness uses to route work and validate output.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_GIT_SHA1_HEX_RE = re.compile(r"^[0-9a-f]{40}$")


class SkillFrontmatter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    resolver: str = Field(min_length=1)
    output_schema_ref: str = Field(min_length=1)
    verifier: str = Field(min_length=1)
    tests_dir: str = Field(min_length=1)


class Skill(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    frontmatter: SkillFrontmatter
    body: str
    git_sha: str

    @field_validator("git_sha")
    @classmethod
    def _v_git_sha(cls, v: str) -> str:
        if not _GIT_SHA1_HEX_RE.match(v):
            raise ValueError("git_sha must be a 40-char lowercase hex git SHA-1")
        return v

    @property
    def skill_id(self) -> str:
        return f"{self.frontmatter.name}@{self.frontmatter.version}"
