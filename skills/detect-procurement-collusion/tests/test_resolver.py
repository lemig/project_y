"""Resolver eval for detect-procurement-collusion.

The planner routes a Brief to a skill by matching `Brief.text` against the
skill's `resolver` regex. This test pins the precision/recall expectation:
the regex must fire for procurement-collusion-shaped briefs and must NOT fire
for briefs that belong to sibling v2 skills (`find-money-flow`,
`find-shell-companies`, `cross-reference-pep`, `narrate-fraud-pattern`,
`summarize-by-entity`, `flag-suspect-doc`).

Per CLAUDE.md, the planner's routing decision is a logged audit-trail event;
a leaky resolver routes the wrong skill and corrupts the trail.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _resolver() -> re.Pattern[str]:
    raw = _SKILL_MD.read_text(encoding="utf-8")
    end = raw.find("\n---\n", len("---\n"))
    parsed = yaml.safe_load(raw[len("---\n") : end])
    return re.compile(parsed["resolver"])


# Briefs that should fire this skill.
_MATCHING_BRIEFS: tuple[str, ...] = (
    "Investigate suspected bid rigging in the 2023 motorway tender awarded by "
    "Ministry of Transport.",
    "We suspect tender collusion among bidders for the IT services framework "
    "agreement.",
    "Look for procurement fraud in the cohesion-fund grants administered by "
    "Region X.",
    "Detect collusive bidders in the road construction tenders awarded by "
    "Ministry of Public Works during 2022-2024.",
    "Identify cover bidding patterns in the 2024 hospital equipment award.",
    "Suspect bid rotation across regional school-renovation tenders.",
    "Bid-rigging cartel suspected across three consecutive defence procurements.",
    "Possible complementary bids in the railway-signalling tender; the runner-up "
    "price is suspiciously high.",
    "Phantom bids: two of the four bidders share an address.",
    "Allegations of public-contract collusion in the wastewater treatment award.",
    # Hyphenated form should match too.
    "Bid-rigging signals in the latest customs-IT tender.",
    # Past-tense form ("rigged"). Resolver must accept it.
    "The auditor flagged the contract as having been bid-rigged.",
)

# Briefs that belong to sibling skills — must NOT fire this resolver.
_NON_MATCHING_BRIEFS: tuple[str, ...] = (
    "Trace the wire transfers from account IT60X0542811101000000123456 to "
    "identify the ultimate beneficiary.",  # find-money-flow
    "Cross-reference the suspect Ivan Petrov against PEP and EU-sanctions "
    "lists.",  # cross-reference-pep
    "Summarize every mention of Acme Srl across the corpus.",  # summarize-by-entity
    "Identify shell companies among the suppliers based on registration "
    "patterns and ownership opacity.",  # find-shell-companies
    "Assemble the grounded notes into a one-page narrative for the case "
    "officer.",  # narrate-fraud-pattern
    "Rank the documents in the corpus by fraud-likelihood and surface the top "
    "five.",  # flag-suspect-doc
    "Find money flow between the offshore entities and the construction "
    "consortium.",
    # Generic English that mentions 'bid' or 'tender' in a non-collusion sense
    # — these would over-fire a too-greedy resolver.
    "What is the highest bid offered at the auction for the Picasso?",
    "Tender chicken breast with rosemary butter — recipe scraped from the suspect's blog.",
    "She made a tender remark about the witness during the hearing.",
)


@pytest.mark.parametrize("brief", _MATCHING_BRIEFS)
def test_resolver_fires_for_collusion_briefs(brief: str) -> None:
    pattern = _resolver()
    assert pattern.search(brief), (
        f"resolver did not fire for collusion-shaped brief: {brief!r}"
    )


@pytest.mark.parametrize("brief", _NON_MATCHING_BRIEFS)
def test_resolver_does_not_fire_for_other_briefs(brief: str) -> None:
    pattern = _resolver()
    assert pattern.search(brief) is None, (
        f"resolver wrongly fired for non-collusion brief: {brief!r}"
    )


def test_resolver_is_case_insensitive() -> None:
    """Investigators don't always title-case their briefs; the regex carries
    the (?i) flag so casing is irrelevant. Pin the behaviour."""
    pattern = _resolver()
    assert pattern.search("BID RIGGING in the 2023 contract")
    assert pattern.search("bid rigging in the 2023 contract")
    assert pattern.search("Bid Rigging in the 2023 contract")
