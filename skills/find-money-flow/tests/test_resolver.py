"""Resolver eval — does the regex fire only on money-trail briefs?

The planner uses the SKILL.md `resolver` regex to route a brief to this
skill. False negatives mean the planner misses the case; false positives
steal work from other skills (e.g. `narrate-fraud-pattern`,
`summarize-by-entity`). Both halves of this test matter.
"""

from __future__ import annotations

import re

import pytest

from _find_money_flow_lib import SKILL_MD, parse_flat_yaml, split_frontmatter


@pytest.fixture(scope="module")
def resolver() -> re.Pattern[str]:
    fm_text, _ = split_frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    return re.compile(parse_flat_yaml(fm_text)["resolver"])


# Briefs that MUST route to find-money-flow.
POSITIVE_BRIEFS = [
    "Trace the money out of contract C-2024-077.",
    "Follow the money from Vesta Holding to the final beneficiary.",
    "trace the funds linked to IBAN IT60X0542811101000000123456",
    "Where did the payments to Polaris Limited come from? Trace the wires.",
    "Money flow analysis for the suspect tender.",
    "We need a money-trail reconstruction over the 12-15 March 2024 window.",
    "Build the transaction chain starting from invoice INV-PL-2024-0042.",
    "Account-to-account trace from Acme Trading to BVI shell.",
    "Trace contract C-2024-077 through all downstream payments.",
    "Wire trace: 250k EUR out of LU28 0019 4006 4475 0000.",
    "Funds flow from the seized cash.",
]


# Briefs that MUST NOT route to find-money-flow — these belong to other
# v2 starter skills (cross-reference-pep, summarize-by-entity,
# detect-procurement-collusion, etc.).
NEGATIVE_BRIEFS = [
    "Summarize what we know about Acme Trading SRL across the corpus.",
    "Is John Smith a politically exposed person?",
    "Detect collusion patterns in the 2023 procurement bundle.",
    "Identify shell-company indicators for Polaris Limited.",
    "Narrate the alleged fraud as a one-page story.",
    "Flag the most suspicious documents in the snapshot.",
    "Does the contract language indicate kickback structuring?",
    "Translate document doc-007 from Italian to English.",
    "Who signed the procurement award?",
]


@pytest.mark.parametrize("brief", POSITIVE_BRIEFS)
def test_resolver_fires_on_money_trail_briefs(
    resolver: re.Pattern[str], brief: str
) -> None:
    assert resolver.search(brief) is not None, (
        f"resolver missed a positive brief: {brief!r}"
    )


@pytest.mark.parametrize("brief", NEGATIVE_BRIEFS)
def test_resolver_does_not_fire_on_unrelated_briefs(
    resolver: re.Pattern[str], brief: str
) -> None:
    assert resolver.search(brief) is None, (
        f"resolver incorrectly fired on unrelated brief: {brief!r}"
    )


def test_resolver_match_is_recoverable_for_audit_trail() -> None:
    """Note.skill_resolver_match must be a non-empty substring of the brief.

    The planner records `match.group(0)` into `Note.skill_resolver_match`
    so an audit reviewer can see WHICH phrasing in the brief routed the
    work here. Verify the match group is non-empty for a realistic brief.
    """
    fm_text, _ = split_frontmatter(SKILL_MD.read_text(encoding="utf-8"))
    pattern = re.compile(parse_flat_yaml(fm_text)["resolver"])
    brief = "Please trace the money from contract C-2024-077."
    m = pattern.search(brief)
    assert m is not None
    assert m.group(0).strip(), "resolver match group(0) was empty/whitespace"
    assert m.group(0) in brief
