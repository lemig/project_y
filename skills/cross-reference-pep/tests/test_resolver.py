"""Resolver eval for cross-reference-pep@v1.

The resolver regex routes briefs to this skill. Per CLAUDE.md and the
SKILL.md body, v2 errs broad — a redundant flag is cheaper than a
silently-skipped entity. These tests pin the broad-but-not-everything
behavior so future tightening (planned for v3) is a deliberate change,
not a drift.
"""

from __future__ import annotations

import re

import pytest

from skills.skill import SkillFrontmatter

# Briefs the resolver MUST fire on. Each pairs a brief with the keyword
# that justifies the match — kept alongside so a future regex change
# that loses a category is obvious in the diff.
POSITIVE_BRIEFS: list[tuple[str, str]] = [
    ("Verify counterparty Acme Corp before approving the contract.", "counterparty / company"),
    ("Screen all directors of TechCo Ltd for PEP exposure.", "screen / director / PEP / company"),
    ("Is John Doe a politically exposed person?", "politically exposed person"),
    ("Run sanctions screening on the wire-transfer beneficiaries.", "sanctions / screening"),
    ("Check this entity against the OFAC SDN list.", "entity"),
    ("KYC review of the new client is overdue.", "KYC / client"),
    ("Identify the beneficial owners of the shell network.", "beneficial owners"),
    ("Cross-reference the shareholders against adverse media.", "shareholders / adverse media"),
    ("Run CDD on the natural person signing the contract.", "CDD / natural person"),
    ("Run AML check on Italian counterparty Società Beta S.r.l.", "counterparty + non-EN entity name"),
    ("Due diligence on the UBO chain.", "due diligence / UBO"),
    ("Apply Wolfsberg guidance to this counterparty review.", "Wolfsberg / counterparty"),
    ("Look up the watchlist status of the contracting officer.", "watchlist / officer"),
]

# Briefs the resolver MUST NOT fire on. The boundary is: nothing in the
# brief mentions a person, a legal person, or screening vocabulary.
NEGATIVE_BRIEFS: list[str] = [
    "Trace the wire transfer of EUR 500,000 across the corpus.",
    "Summarize the 2023 financial year filings.",
    "Extract page 5 from contract_2021_044.pdf.",
    "Compute the total invoice amount per quarter.",
    "What is the date range of documents in this snapshot?",
    "Find all references to invoice number INV-2021-0099.",
    "List the OCR-failed pages so we can re-extract them.",
]


@pytest.fixture(scope="module")
def resolver(skill_frontmatter: dict) -> re.Pattern[str]:
    fm = SkillFrontmatter(**skill_frontmatter)
    return re.compile(fm.resolver)


@pytest.mark.parametrize("brief,why", POSITIVE_BRIEFS)
def test_resolver_fires_on_positive_brief(
    resolver: re.Pattern[str], brief: str, why: str
) -> None:
    assert resolver.search(brief) is not None, (
        f"resolver did not fire on a brief it should match ({why}): {brief!r}"
    )


@pytest.mark.parametrize("brief", NEGATIVE_BRIEFS)
def test_resolver_does_not_fire_on_negative_brief(
    resolver: re.Pattern[str], brief: str
) -> None:
    assert resolver.search(brief) is None, (
        f"resolver fired on a brief it should not match: {brief!r}"
    )


def test_resolver_is_case_insensitive(resolver: re.Pattern[str]) -> None:
    assert resolver.search("PEP screening required") is not None
    assert resolver.search("pep screening required") is not None
    assert resolver.search("Pep Screening Required") is not None


def test_resolver_match_is_word_bounded(resolver: re.Pattern[str]) -> None:
    """'pepperoni' contains 'pep' as a substring but is not a PEP. The
    regex uses \\b boundaries to avoid this class of false positive."""
    assert resolver.search("pepperoni pizza order") is None
    assert resolver.search("client management") is not None
