"""Resolver eval for flag-suspect-doc.

Pins the contract that the planner uses to route briefs to this skill: must
fire on doc-ranking / fraud-flagging requests, must NOT fire on briefs
better served by the other v2 starter skills (find-money-flow,
summarize-by-entity, cross-reference-pep, find-shell-companies, ...).

These cases ARE the resolver eval; tightening the regex without updating
this list is what causes silent routing drift across deps upgrades.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"
_FRONTMATTER_OPEN = "---\n"
_FRONTMATTER_CLOSE = "\n---\n"


def _load_resolver() -> re.Pattern[str]:
    raw = _SKILL_MD.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    end = raw.find(_FRONTMATTER_CLOSE, len(_FRONTMATTER_OPEN))
    fm = yaml.safe_load(raw[len(_FRONTMATTER_OPEN) : end])
    return re.compile(fm["resolver"])


# Briefs that MUST route to flag-suspect-doc.
POSITIVE_BRIEFS: tuple[str, ...] = (
    "Rank these documents by fraud likelihood.",
    "Flag suspect documents in the 2023 procurement corpus.",
    "Score documents for fraud risk.",
    "Which documents look most suspicious in the Acme tender?",
    "Find documents with high fraud risk relating to vendor X.",
    "Identify anomalous documents in the corpus.",
    "list all suspect docs",
    "These DOCUMENTS show suspicious wire transfers.",
    "Surface red-flagged docs first.",
    "Show high-risk documents from Q3.",
    "highlight the most fraudulent documents",
    "Flag documents with anomalies in invoice numbering.",
)

# Briefs that MUST NOT route to flag-suspect-doc — they belong to other v2
# starter skills or are out of scope. Tighten the regex if any of these
# accidentally match.
NEGATIVE_BRIEFS: tuple[str, ...] = (
    "Trace the money flow from Account A to Account B.",
    "Summarize all documents mentioning Acme Corp.",
    "Translate the Italian invoices into English.",
    "List the parties named in document 5.",
    "Find shell companies in the registry.",
    "Cross-reference these entities with PEP lists.",
    "Detect procurement collusion across these tenders.",
    "Narrate the fraud pattern from the notes you already have.",
    "Summarize entity Acme Corp across the corpus.",
    "Who signed the 2023 contract with Vendor Y?",
)


@pytest.fixture(scope="module")
def resolver() -> re.Pattern[str]:
    return _load_resolver()


@pytest.mark.parametrize("brief", POSITIVE_BRIEFS)
def test_resolver_fires_on_in_scope_briefs(resolver: re.Pattern[str], brief: str) -> None:
    assert resolver.search(brief) is not None, f"resolver should fire for: {brief!r}"


@pytest.mark.parametrize("brief", NEGATIVE_BRIEFS)
def test_resolver_does_not_fire_on_out_of_scope_briefs(
    resolver: re.Pattern[str], brief: str
) -> None:
    assert resolver.search(brief) is None, f"resolver should NOT fire for: {brief!r}"


def test_resolver_is_case_insensitive(resolver: re.Pattern[str]) -> None:
    assert resolver.search("RANK THESE DOCUMENTS BY FRAUD LIKELIHOOD") is not None
    assert resolver.search("rank these documents by fraud likelihood") is not None


def test_resolver_match_substring_is_recordable(resolver: re.Pattern[str]) -> None:
    # The Note's `skill_resolver_match` field requires a non-empty string.
    # Whatever the regex captures must satisfy that constraint so the audit
    # log can record it without further conditioning.
    m = resolver.search("Flag suspect documents in this case.")
    assert m is not None
    assert len(m.group(0)) >= 1
