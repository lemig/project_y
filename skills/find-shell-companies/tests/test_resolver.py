"""Resolver eval for find-shell-companies.

The resolver is a regex applied to brief text. The planner uses it to
decide whether to route a brief to this skill. This test pins:

1. SHOULD-FIRE briefs all match (no false negatives on canonical phrasings —
   that is the failure mode that loses notes).
2. SHOULD-NOT-FIRE briefs do not match (the planner won't drown the agent
   in spurious skill routing).

False positives are tolerable (the planner can dispatch multiple skills);
false negatives are not (an investigation that should have surfaced shell
indicators silently won't).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_SKILL_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"


def _resolver() -> re.Pattern[str]:
    raw = _SKILL_PATH.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    end = raw.find("\n---\n", len("---\n"))
    front = raw[len("---\n") : end]
    parsed = yaml.safe_load(front)
    return re.compile(parsed["resolver"])


# Briefs the planner MUST route to find-shell-companies.
SHOULD_FIRE = [
    "find shell companies among the suppliers in this tender",
    "are any of these vendors shell corporations",
    "screen for letterbox companies in the contractor list",
    "look for mailbox entities in this corpus",
    "identify front companies receiving payments",
    "check for nominee directors across these vendors",
    "any fictitious companies in the bidder list?",
    "investigate beneficial ownership of the contracted parties",
    "are these entities hiding their UBO",
    "trace the beneficial-ownership chain for these suppliers",
    "find opaque ownership in the procurement vendors",
    "any hidden ownership in the supplier network",
    "screen the vendors for hidden owners",
    "look for mass-incorporation patterns in these registrations",
    "any registered-agent addresses recurring across these suppliers",
    # Mixed-case + punctuation
    "Find SHELL companies in the tender bids.",
    "Identify the Beneficial Ownership of these contractors.",
    "Are any of the suppliers Letterbox Companies?",
]

# Briefs the planner MUST NOT route to find-shell-companies.
SHOULD_NOT_FIRE = [
    "trace the money flow from contract A to bank account B",
    "summarize all documents mentioning ACME Holdings",
    "detect tender rigging in the public procurement file",
    "narrate the fraud pattern in this case",
    "rank documents by suspicion",
    "list every payment over 10,000 EUR",
    "find the contract amendments signed in 2023",
    "extract the list of subcontractors",
    "who signed the invoice on page 4",
    "translate the Romanian invoice to English",
    "map the corporate hierarchy of Banca Intesa",
    "what is the project value of contract R-7741",
    # The word 'shell' in unrelated context — pure pattern-match will fire,
    # but the skill body and substring verifier downstream will fail
    # gracefully. We do NOT include "Royal Dutch Shell" here as a
    # should-not-fire — the resolver is a coarse routing filter, not the
    # arbiter of relevance, and that distinction is OK per the skill body.
]


@pytest.mark.parametrize("brief", SHOULD_FIRE)
def test_resolver_fires_on_canonical_briefs(brief: str) -> None:
    pattern = _resolver()
    assert pattern.search(brief), (
        f"resolver MUST match brief but did not: {brief!r}"
    )


@pytest.mark.parametrize("brief", SHOULD_NOT_FIRE)
def test_resolver_does_not_fire_on_unrelated_briefs(brief: str) -> None:
    pattern = _resolver()
    match = pattern.search(brief)
    assert match is None, (
        f"resolver matched unrelated brief {brief!r} on substring {match.group(0)!r}"
    )


def test_resolver_returns_a_match_object_with_a_substring() -> None:
    """The harness records `Note.skill_resolver_match` as the substring that
    fired. Ensure resolver.search returns a non-empty group when it matches.
    """
    pattern = _resolver()
    m = pattern.search("find shell companies in the tender")
    assert m is not None
    assert m.group(0), "resolver match must capture at least one character"
