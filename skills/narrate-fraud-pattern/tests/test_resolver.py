"""Resolver eval for narrate-fraud-pattern.

The planner routes a brief to a skill by matching `resolver` against the
brief text. This file is the resolver-eval corpus: positive briefs MUST
match, negative briefs MUST NOT match. If either side drifts, the planner
will silently misroute and we lose the audit-trail invariant that every
note carries a `skill_resolver_match`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent.deep_agents_harness import _parse_frontmatter, _split_frontmatter

_SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"


def _resolver() -> re.Pattern[str]:
    text = _SKILL_MD.read_text(encoding="utf-8-sig")
    front, _ = _split_frontmatter(text)
    fm = _parse_frontmatter(front)
    return re.compile(fm.resolver)


# Briefs that SHOULD route to narrate-fraud-pattern.
POSITIVES = [
    "Narrate the fraud pattern from these notes.",
    "Tell the story of the suspected scheme.",
    "Produce a 1-page narrative of the case.",
    "Give me a 1 page summary of what happened.",
    "Summarize the fraud pattern across the documents.",
    "Summarise the case for an investigator unfamiliar with it.",
    "Write up the case as a chronological story.",
    "Writeup the alleged scheme against budget line BL-12.",
    "I need a case summary for the briefing.",
    "Narration of the events between 2023 and 2024, please.",
    "Summarize the scheme implicating Vendor X.",
]


# Briefs that should NOT route here — they belong to other v2 skills
# (find-money-flow, find-shell-companies, summarize-by-entity, etc.)
NEGATIVES = [
    "Trace the 120k from contract X to the final beneficiary.",
    "Find shell companies registered in the same week as Acme Holdings.",
    "Detect procurement collusion in tender T-2024-118.",
    "Cross-reference all natural persons against the OpenSanctions list.",
    "Flag the most suspect documents in this corpus.",
    # 'summarize-by-entity' is a different skill — it answers "what does
    # the corpus say about entity E?", not "tell the story of the case".
    "Summarize the corpus by entity.",
    "List all entities mentioned in doc-42.",
    "What does the corpus say about Banca Intesa?",
    "Show me the money flow from account A to account B.",
]


@pytest.mark.parametrize("brief", POSITIVES)
def test_resolver_fires_on_positive_briefs(brief: str) -> None:
    assert _resolver().search(brief) is not None, (
        f"narrate-fraud-pattern resolver should match: {brief!r}"
    )


@pytest.mark.parametrize("brief", NEGATIVES)
def test_resolver_does_not_fire_on_negative_briefs(brief: str) -> None:
    assert _resolver().search(brief) is None, (
        f"narrate-fraud-pattern resolver should NOT match: {brief!r}"
    )


def test_resolver_is_case_insensitive() -> None:
    pattern = _resolver()
    assert pattern.search("NARRATE the case") is not None
    assert pattern.search("Tell The Story of the scheme") is not None
