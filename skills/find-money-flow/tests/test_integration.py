"""Integration / LLM-eval baseline for find-money-flow.

The harness adapter + substring quote verifier are landing in parallel
PRs. Until they're wired in, this test is the **golden-run replay
target**: the Notes that the LLM-driven planner is expected to emit for
the fixture corpus. The test:

1. Loads the fixture documents and computes their normalized-text
   sha256 + per-quote char offsets — exactly what the substring quote
   verifier will do at runtime.
2. Builds the expected hop chain as Note objects, which forces the
   schema to validate every quote (offsets, sha256, source-language,
   translator-of-record contract).
3. Asserts chain coherence: each hop's destination account matches the
   next hop's source account, and every quote sits at real offsets in
   real fixture text.

When the LLM-driven planner lands, its output for the same fixture
corpus + brief will be diffed against this baseline (golden-run replay
per CLAUDE.md). Drift = CI fail.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest

# Reuse the harness's git-blob SHA helper so test-computed skill_version
# matches what `DeepAgentsHarness.load_skill` produces at runtime —
# golden-replay-equivalent.
from agent.deep_agents_harness import _git_blob_sha1
from schema.brief import Brief
from schema.note import Note, Quote

_SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@dataclass(frozen=True)
class _Doc:
    doc_id: str
    text: str
    path: Path
    sha256: str

    @classmethod
    def load(cls, doc_id: str, filename: str) -> "_Doc":
        path = _FIXTURES / filename
        text = path.read_text(encoding="utf-8")
        return cls(doc_id=doc_id, text=text, path=path, sha256=_sha256(text.encode("utf-8")))


@dataclass(frozen=True)
class _ExpectedHop:
    """One hop the LLM-driven planner is expected to emit for the fixture."""

    claim: str
    why_relevant: str
    confidence: float
    source_account: str
    destination_account: str
    quote_text: str  # MUST be a verbatim substring of doc.text
    source_lang: str
    quote_text_en: str | None
    translator_of_record: str | None
    doc: _Doc


@pytest.fixture(scope="module")
def docs() -> dict[str, _Doc]:
    return {
        "doc-001": _Doc.load("doc-001", "doc-001.txt"),
        "doc-002": _Doc.load("doc-002", "doc-002.txt"),
        "doc-003": _Doc.load("doc-003", "doc-003.txt"),
    }


@pytest.fixture(scope="module")
def brief() -> Brief:
    # The corpus_snapshot_hash here is a stand-in for the real per-investigation
    # snapshot hash that the snapshot module produces; locally we hash the
    # concatenation of the three fixture files in id-sorted order so the
    # baseline is reproducible.
    fixture_blob = b"".join(
        (_FIXTURES / f).read_bytes() for f in ("doc-001.txt", "doc-002.txt", "doc-003.txt")
    )
    return Brief(
        text="Trace the money out of contract C-2024-077.",
        corpus_snapshot_hash=_sha256(fixture_blob),
        locale="en",
    )


@pytest.fixture(scope="module")
def expected_hops(docs: dict[str, _Doc]) -> list[_ExpectedHop]:
    return [
        _ExpectedHop(
            claim=(
                "Acme Trading SRL transferred EUR 250.000,00 from "
                "IT60X0542811101000000123456 to LU28 0019 4006 4475 0000 "
                "(Vesta Holding SA) on 12 March 2024 per contract C-2024-077."
            ),
            why_relevant=(
                "Hop 1 of the chain anchored on contract C-2024-077 — "
                "the brief's starting reference."
            ),
            confidence=1.0,
            source_account="IT60X0542811101000000123456",
            destination_account="LU28 0019 4006 4475 0000",
            quote_text=(
                "Banca Intesa Sanpaolo conferma il trasferimento di "
                "EUR 250.000,00 dal conto IT60X0542811101000000123456 "
                "(Acme Trading SRL) al conto LU28 0019 4006 4475 0000 "
                "(Vesta Holding SA) in data 12 marzo 2024, "
                "riferimento contratto C-2024-077."
            ),
            source_lang="it",
            quote_text_en=(
                "Banca Intesa Sanpaolo confirms the transfer of "
                "EUR 250,000.00 from account IT60X0542811101000000123456 "
                "(Acme Trading SRL) to account LU28 0019 4006 4475 0000 "
                "(Vesta Holding SA) on 12 March 2024, "
                "reference contract C-2024-077."
            ),
            translator_of_record="argos-translate-1.9@it-en",
            doc=docs["doc-001"],
        ),
        _ExpectedHop(
            claim=(
                "Vesta Holding SA forwarded EUR 248,500 from "
                "LU28 0019 4006 4475 0000 to BVI-NB-99281 "
                "(Polaris Limited) on 13 March 2024 per "
                "invoice INV-PL-2024-0042."
            ),
            why_relevant=(
                "Hop 2 — destination of hop 1 (LU account) is the "
                "source of this hop. Same-day-plus-one transfer with "
                "a ~1.5k EUR drop is consistent with intermediary fees."
            ),
            confidence=1.0,
            source_account="LU28 0019 4006 4475 0000",
            destination_account="BVI-NB-99281",
            quote_text=(
                "On 13 March 2024, Vesta Holding SA forwarded EUR 248,500 "
                "from account LU28 0019 4006 4475 0000 to BVI-registered "
                "Polaris Limited (account: BVI-NB-99281) for invoice "
                "INV-PL-2024-0042 (consultancy services)."
            ),
            source_lang="en",
            quote_text_en=None,
            translator_of_record=None,
            doc=docs["doc-002"],
        ),
        _ExpectedHop(
            claim=(
                "Polaris Limited withdrew EUR 245,000 in cash from "
                "BVI-NB-99281 on 15 March 2024 at Northern Bank Tortola "
                "branch (slip CW-99281-150324)."
            ),
            why_relevant=(
                "Hop 3 — terminal cash-out closes the trail. Three "
                "hops in four days with no apparent economic substance "
                "matches the FATF Methodology layering pattern; stop "
                "condition #3 fires."
            ),
            confidence=1.0,
            source_account="BVI-NB-99281",
            destination_account="CASH",
            quote_text=(
                "Polaris Limited withdrew EUR 245,000 in cash from "
                "account BVI-NB-99281 on 15 March 2024 at the Tortola "
                "branch of Northern Bank."
            ),
            source_lang="en",
            quote_text_en=None,
            translator_of_record=None,
            doc=docs["doc-003"],
        ),
    ]


def _build_note(
    hop: _ExpectedHop,
    *,
    brief_hash: str,
    corpus_hash: str,
    skill_version: str,
    resolver_match: str,
) -> Note:
    start = hop.doc.text.find(hop.quote_text)
    if start < 0:
        raise AssertionError(
            f"expected quote not found verbatim in {hop.doc.doc_id}: "
            f"{hop.quote_text!r}"
        )
    end = start + len(hop.quote_text)
    quote = Quote(
        quote_text=hop.quote_text,
        quote_text_en=hop.quote_text_en,
        doc_id=hop.doc.doc_id,
        page=1,
        char_offset_start=start,
        char_offset_end=end,
        extractor_version="aleph-text-extract-3.18",
        normalized_text_sha256=hop.doc.sha256,
        source_lang=hop.source_lang,
        translator_of_record=hop.translator_of_record,
    )
    return Note(
        claim=hop.claim,
        exact_quotes=(quote,),
        confidence=hop.confidence,
        why_relevant=hop.why_relevant,
        source_corpus_snapshot_hash=corpus_hash,
        brief_hash=brief_hash,
        skill_id="find-money-flow@v1",
        skill_resolver_match=resolver_match,
        skill_version=skill_version,
    )


def test_fixture_chain_builds_valid_notes(
    brief: Brief, expected_hops: list[_ExpectedHop]
) -> None:
    skill_version = _git_blob_sha1(_SKILL_MD.read_bytes())
    notes = [
        _build_note(
            h,
            brief_hash=brief.compute_hash(),
            corpus_hash=brief.corpus_snapshot_hash,
            skill_version=skill_version,
            resolver_match="trace the money",
        )
        for h in expected_hops
    ]
    assert len(notes) == 3
    for n in notes:
        assert n.tier == "investigation"
        assert n.skill_id == "find-money-flow@v1"
        assert len(n.exact_quotes) >= 1


def test_fixture_chain_is_coherent(expected_hops: list[_ExpectedHop]) -> None:
    """Hop n's destination must equal hop n+1's source."""
    for prev, nxt in zip(expected_hops, expected_hops[1:]):
        assert prev.destination_account == nxt.source_account, (
            f"chain broken: {prev.destination_account!r} -> "
            f"{nxt.source_account!r}"
        )


def test_every_quote_exists_verbatim_in_its_source_doc(
    expected_hops: list[_ExpectedHop],
) -> None:
    """Mirrors the substring quote verifier's hard gate."""
    for h in expected_hops:
        assert h.quote_text in h.doc.text, (
            f"quote not a substring of {h.doc.doc_id}: {h.quote_text!r}"
        )


def test_non_english_quote_carries_translator_of_record(
    expected_hops: list[_ExpectedHop],
) -> None:
    """Multilingual contract from CLAUDE.md note 6."""
    for h in expected_hops:
        if h.source_lang == "en":
            assert h.translator_of_record is None
            assert h.quote_text_en is None
        else:
            assert h.translator_of_record is not None
            assert h.quote_text_en is not None


def test_layering_pattern_present_in_fixture(
    expected_hops: list[_ExpectedHop],
) -> None:
    """Sanity: the fixture really does encode a 3-hop layering pattern.

    Per FATF Methodology, layering = rapid pass-through with declining
    amounts. We don't run the LLM here — we just assert the fixture
    sequence is what the methodology body's stop condition #3 should
    fire on.
    """
    assert len(expected_hops) == 3
    # Strictly declining intermediate balances (250k → 248.5k → 245k cash).
    # Coded as 'amount appears in the quote text' to keep the test robust
    # to claim phrasing changes.
    assert "250.000,00" in expected_hops[0].quote_text
    assert "248,500" in expected_hops[1].quote_text
    assert "245,000" in expected_hops[2].quote_text
