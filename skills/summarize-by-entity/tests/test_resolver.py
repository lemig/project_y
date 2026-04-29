"""Resolver eval for the summarize-by-entity skill.

Confirms the resolver fires on the brief shapes analysts actually write
("summarize what we know about Acme", "build a dossier on John Smith")
and stays silent on briefs that belong to sibling skills (money-flow
tracing, shell-company detection, fraud-narrative assembly, collusion
detection, PEP cross-referencing). Resolver collisions across skills are
how the planner double-fires and bills two LLM rounds for one job, so
the negative cases are as load-bearing as the positives.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture(scope="module")
def resolver(parsed_skill) -> re.Pattern[str]:
    return re.compile(parsed_skill["frontmatter"]["resolver"])


# Each tuple: (brief_text, why-it-must-match-rationale)
POSITIVE_BRIEFS: list[tuple[str, str]] = [
    (
        "Summarize what we know about Acme Holdings Ltd.",
        "canonical 'summarize ... about <entity>' phrasing",
    ),
    (
        "summarize what we know about Acme Holdings Ltd.",
        "lowercase variant — case-insensitive",
    ),
    (
        "SUMMARIZE WHAT WE KNOW ABOUT ACME HOLDINGS LTD",
        "uppercase variant — case-insensitive",
    ),
    (
        "Give me a profile of John Smith.",
        "'profile of <person>'",
    ),
    (
        "Build a dossier on XYZ Holdings.",
        "'dossier on <entity>'",
    ),
    (
        "I need a summary of Banca Intesa across the corpus.",
        "'summary of <entity>'",
    ),
    (
        "What do we know about the company Gamma Trading?",
        "'what do we know about <entity>'",
    ),
    (
        "What have we learned about John Smith so far?",
        "'what have we learned about <entity>'",
    ),
    (
        "What did we know about that account at filing time?",
        "'what did we know about <noun>'",
    ),
    (
        "Background on the contracting party Beta Logistics, please.",
        "'background on <entity>'",
    ),
    (
        "Summarise per entity the wires found in the bank export.",
        "British spelling 'summarise' + 'per entity'",
    ),
    (
        "Summarize by entity what mentions exist.",
        "'summarize by entity'",
    ),
    (
        "Build a profile for the subject of this case.",
        "'profile for <noun>'",
    ),
]

# Negative cases: briefs that belong to sibling v2 skills.
NEGATIVE_BRIEFS: list[tuple[str, str]] = [
    (
        "Trace the money flow from Acme Holdings to its counterparties.",
        "find-money-flow territory — no synthesis verb",
    ),
    (
        "Find shell companies registered in Cyprus among the parties.",
        "find-shell-companies — no synthesis verb",
    ),
    (
        "Detect procurement collusion in the tender file set.",
        "detect-procurement-collusion — 'detect' is not a synthesis verb",
    ),
    (
        "Narrate the fraud pattern across the four contracts.",
        "narrate-fraud-pattern — no synthesis verb in our resolver alternation",
    ),
    (
        "Cross-reference the directors against PEP and sanctions lists.",
        "cross-reference-pep — no synthesis verb",
    ),
    (
        "Flag suspect documents in the corpus.",
        "flag-suspect-doc — no synthesis verb",
    ),
    (
        "Summarize the case so far.",
        "synthesis verb present, but no per-entity preposition / qualifier — "
        "this is narrate-fraud-pattern's territory, not ours",
    ),
    (
        "Summarize the contract.",
        "same as above — 'the contract' is not a per-entity ask",
    ),
    (
        "List all documents mentioning Acme.",
        "'list' is not a synthesis verb",
    ),
    (
        "Find all wire transfers above 50,000 EUR.",
        "different skill family entirely",
    ),
    (
        "What do we know?",
        "synthesis lead-in but no 'about <X>' tail — ambiguous, must not fire",
    ),
]


@pytest.mark.parametrize(
    "brief,why",
    POSITIVE_BRIEFS,
    ids=[f"pos[{i}]" for i in range(len(POSITIVE_BRIEFS))],
)
def test_resolver_fires_on_synthesis_briefs(
    resolver: re.Pattern[str], brief: str, why: str
) -> None:
    assert resolver.search(brief) is not None, (
        f"resolver should fire on this brief — {why}\nbrief: {brief!r}"
    )


@pytest.mark.parametrize(
    "brief,why",
    NEGATIVE_BRIEFS,
    ids=[f"neg[{i}]" for i in range(len(NEGATIVE_BRIEFS))],
)
def test_resolver_does_not_fire_on_sibling_skill_briefs(
    resolver: re.Pattern[str], brief: str, why: str
) -> None:
    assert resolver.search(brief) is None, (
        f"resolver should NOT fire on this brief — {why}\nbrief: {brief!r}"
    )


def test_resolver_fires_on_multilingual_brief_text(
    resolver: re.Pattern[str],
) -> None:
    # The brief is English-only by project policy (CLAUDE.md §6: "UI is
    # English-only"), but analysts paste in non-EN entity names. The
    # resolver must still fire when the entity name itself contains
    # non-ASCII characters.
    brief = "Summarize what we know about Société Générale Côte d'Ivoire."
    assert resolver.search(brief) is not None
