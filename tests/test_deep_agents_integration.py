"""Live-endpoint integration test for `DeepAgentsHarness`.

Skipped unless `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` are all set in
the environment, so unit-test runs in CI / on dev workstations stay offline.

Mark with `pytest -m integration` to run; `pytest -m "not integration"`
(or simply the default) to skip.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.deep_agents_harness import DeepAgentsHarness
from agent.harness import PlannerResult
from schema.brief import Brief

_REQUIRED_ENV = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")
_BRIEF_HASH = "d" * 64

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not all(k in os.environ for k in _REQUIRED_ENV),
        reason=(
            "Set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL to run live-endpoint "
            "integration tests."
        ),
    ),
]


def test_planner_run_against_live_endpoint(tmp_path: Path) -> None:
    h = DeepAgentsHarness(
        skills_root=tmp_path / "skills",
        checkpoints_dir=tmp_path / "ck",
        # model=None forces the env-var construction path
    )
    brief = Brief(
        text="Reply with exactly the single word: ACK.",
        corpus_snapshot_hash=_BRIEF_HASH,
    )
    result = h.planner_run(brief)

    assert isinstance(result, PlannerResult)
    # The deep-agent state always includes the input message, so the plan_log
    # is non-empty for any successful round-trip.
    assert len(result.plan_log) >= 1
    assert h._state.last_brief_hash == brief.compute_hash()


def test_checkpoint_after_live_run(tmp_path: Path) -> None:
    h = DeepAgentsHarness(
        skills_root=tmp_path / "skills",
        checkpoints_dir=tmp_path / "ck",
    )
    h.planner_run(
        Brief(text="Say only: OK.", corpus_snapshot_hash=_BRIEF_HASH)
    )
    cid = h.checkpoint()
    assert (tmp_path / "ck" / f"{cid}.json").is_file()
