"""Integration / LLM eval contract for narrate-fraud-pattern.

This skill is pure synthesis: it consumes upstream `Note`s and emits a
single narrative `Note` whose `exact_quotes` are inherited verbatim from
the inputs. The structural part of that contract — quote inheritance,
minimum-confidence rule, single-snapshot rule, multilingual + translation
preservation — is deterministic and must hold without ever calling the
LLM. We pin those properties below as a spec-by-example so the eventual
LLM-driven implementation has a concrete target to land against.

The live-LLM eval (which judges narrative quality, the part that is
genuinely non-deterministic) is gated behind the `integration` mark and
the `LLM_*` env vars, mirroring `tests/test_deep_agents_integration.py`.
It is a no-op skip until the v2 skill-routing pipeline is wired in
(`spawn_subagent` → load SKILL.md → planner-driven synthesis), and
documents the precondition for that future plumbing.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import pytest
from pydantic import ValidationError

from schema.note import Note, Quote

_SKILL_ID = "narrate-fraud-pattern@v1"
_SKILL_RESOLVER_MATCH = "narrate the fraud pattern"
_GIT_SHA = hashlib.sha1(b"narrate-fraud-pattern-v1").hexdigest()
_CORPUS = hashlib.sha256(b"corpus-snapshot").hexdigest()
_BRIEF = hashlib.sha256(b"brief-text").hexdigest()


def _quote(
    quote_text: str,
    *,
    doc_id: str,
    char_offset_start: int,
    char_offset_end: int,
    page: int | None = None,
    source_lang: str = "en",
    quote_text_en: str | None = None,
    translator_of_record: str | None = None,
) -> Quote:
    return Quote(
        quote_text=quote_text,
        quote_text_en=quote_text_en,
        doc_id=doc_id,
        page=page,
        char_offset_start=char_offset_start,
        char_offset_end=char_offset_end,
        extractor_version="tesseract-5.3.1@aleph-3.18",
        normalized_text_sha256=hashlib.sha256(
            quote_text.encode("utf-8")
        ).hexdigest(),
        source_lang=source_lang,
        translator_of_record=translator_of_record,
    )


def _input_note(
    *,
    skill_id: str,
    claim: str,
    quotes: tuple[Quote, ...],
    confidence: float,
    why_relevant: str,
    corpus: str = _CORPUS,
) -> Note:
    return Note(
        claim=claim,
        exact_quotes=quotes,
        confidence=confidence,
        why_relevant=why_relevant,
        source_corpus_snapshot_hash=corpus,
        brief_hash=_BRIEF,
        skill_id=skill_id,
        skill_resolver_match=skill_id.split("@")[0],
        skill_version=_GIT_SHA,
    )


@pytest.fixture
def fixture_corpus() -> tuple[Note, ...]:
    """Three synthetic upstream notes spanning EN, IT, and a failed translation.

    Drawn from public investigative-typology phrasings (bid-rigging, layered
    transfer, shell-company registration). No real entities or case material.
    """
    money_flow_quote = _quote(
        "Banca Intesa transferred 120,000 EUR to ACME Holdings on 2024-03-12",
        doc_id="doc-A",
        page=2,
        char_offset_start=58,
        char_offset_end=124,
    )
    procurement_quote = _quote(
        # Italian source + English translation; well-formed translator pair.
        "Il fornitore X ha presentato un'offerta superiore dello 0,4% rispetto a Y",
        quote_text_en="Vendor X submitted a bid 0.4% higher than Vendor Y",
        doc_id="doc-B",
        page=1,
        char_offset_start=200,
        char_offset_end=276,
        source_lang="it",
        translator_of_record="argos-1.9",
    )
    shell_quote = _quote(
        # Romanian source where the translator failed; the failure marker
        # MUST survive into the synthesized Note unchanged.
        "ACME Holdings a fost înregistrată în aceeași săptămână cu trei alte societăți",
        doc_id="doc-C",
        page=None,
        char_offset_start=12,
        char_offset_end=88,
        source_lang="ro",
        translator_of_record="argos-1.9:translation_failed",
    )

    money_flow = _input_note(
        skill_id="find-money-flow@v1",
        claim="120k EUR moved from Banca Intesa to ACME Holdings on 2024-03-12.",
        quotes=(money_flow_quote,),
        confidence=0.92,
        why_relevant="Establishes the contested transfer.",
    )
    procurement = _input_note(
        skill_id="detect-procurement-collusion@v1",
        claim="Vendor X bid was 0.4% above Vendor Y — complementary-bidding signal.",
        quotes=(procurement_quote,),
        confidence=0.71,
        why_relevant="Bid pattern matches OECD complementary-bidding typology.",
    )
    shell = _input_note(
        skill_id="find-shell-companies@v1",
        claim="ACME Holdings registered the same week as three other entities.",
        quotes=(shell_quote,),
        confidence=0.64,
        why_relevant="Registration clustering is a known shell-company indicator.",
    )
    return (money_flow, procurement, shell)


def _expected_synthesis(inputs: tuple[Note, ...]) -> Note:
    """Hand-built expected output for the fixture corpus.

    This is the contract narrate-fraud-pattern@v1 must honour: union of
    input quotes (deduplicated on (doc_id, char_offset_start,
    char_offset_end)), confidence = min(input confidences), single
    snapshot, transitive grounding. The narrative prose (`claim`,
    `why_relevant`) is the LLM-driven part and is deliberately
    placeholdered here.
    """
    seen: set[tuple[str, int, int]] = set()
    inherited: list[Quote] = []
    for n in inputs:
        for q in n.exact_quotes:
            key = (q.doc_id, q.char_offset_start, q.char_offset_end)
            if key in seen:
                continue
            seen.add(key)
            inherited.append(q)

    snapshots = {n.source_corpus_snapshot_hash for n in inputs}
    assert len(snapshots) == 1, (
        "narrate-fraud-pattern refuses to synthesize across mismatched "
        "corpus-snapshot hashes"
    )

    return Note(
        claim=(
            "ACME Holdings received a 120k EUR transfer days after a "
            "complementary-bid pattern at Vendor X, with shell-company "
            "registration timing flagged."
        ),
        exact_quotes=tuple(inherited),
        confidence=min(n.confidence for n in inputs),
        why_relevant=(
            "Chronological synthesis tying the procurement signal to the "
            "downstream transfer and to the shell-company indicator."
        ),
        source_corpus_snapshot_hash=snapshots.pop(),
        brief_hash=_BRIEF,
        skill_id=_SKILL_ID,
        skill_resolver_match=_SKILL_RESOLVER_MATCH,
        skill_version=_GIT_SHA,
    )


class TestSynthesisContract:
    """Deterministic structural properties — no LLM required."""

    def test_output_passes_note_schema(self, fixture_corpus: tuple[Note, ...]) -> None:
        Note(**_expected_synthesis(fixture_corpus).model_dump())

    def test_skill_id_and_tier(self, fixture_corpus: tuple[Note, ...]) -> None:
        out = _expected_synthesis(fixture_corpus)
        assert out.skill_id == _SKILL_ID
        assert out.tier == "investigation"

    def test_every_input_quote_is_inherited(
        self, fixture_corpus: tuple[Note, ...]
    ) -> None:
        out = _expected_synthesis(fixture_corpus)
        out_keys = {
            (q.doc_id, q.char_offset_start, q.char_offset_end)
            for q in out.exact_quotes
        }
        for n in fixture_corpus:
            for q in n.exact_quotes:
                assert (
                    q.doc_id,
                    q.char_offset_start,
                    q.char_offset_end,
                ) in out_keys, (
                    f"input quote {q.doc_id}:{q.char_offset_start}-"
                    f"{q.char_offset_end} not inherited into narrative"
                )

    def test_quotes_are_byte_exact_inheritance(
        self, fixture_corpus: tuple[Note, ...]
    ) -> None:
        # Build an index of input quotes; every output quote must equal
        # one of them (Pydantic frozen + extra=forbid → __eq__ is total).
        input_quotes = {
            (q.doc_id, q.char_offset_start, q.char_offset_end): q
            for n in fixture_corpus
            for q in n.exact_quotes
        }
        out = _expected_synthesis(fixture_corpus)
        for q in out.exact_quotes:
            key = (q.doc_id, q.char_offset_start, q.char_offset_end)
            assert key in input_quotes, "phantom quote in output"
            assert q == input_quotes[key], (
                "output quote drifted from input — narrate-fraud-pattern "
                "must inherit byte-exact, not re-derive"
            )

    def test_confidence_is_minimum_of_inputs(
        self, fixture_corpus: tuple[Note, ...]
    ) -> None:
        out = _expected_synthesis(fixture_corpus)
        assert out.confidence == min(n.confidence for n in fixture_corpus)
        assert out.confidence <= max(n.confidence for n in fixture_corpus)

    def test_translation_failure_marker_survives(
        self, fixture_corpus: tuple[Note, ...]
    ) -> None:
        out = _expected_synthesis(fixture_corpus)
        ro_quotes = [q for q in out.exact_quotes if q.source_lang == "ro"]
        assert len(ro_quotes) == 1
        assert ro_quotes[0].quote_text_en is None
        assert ro_quotes[0].translator_of_record == "argos-1.9:translation_failed"

    def test_well_formed_translation_pair_survives(
        self, fixture_corpus: tuple[Note, ...]
    ) -> None:
        out = _expected_synthesis(fixture_corpus)
        it_quotes = [q for q in out.exact_quotes if q.source_lang == "it"]
        assert len(it_quotes) == 1
        assert it_quotes[0].quote_text_en is not None
        assert it_quotes[0].translator_of_record == "argos-1.9"

    def test_single_snapshot_invariant_enforced(
        self, fixture_corpus: tuple[Note, ...]
    ) -> None:
        # Mutate one input to a different snapshot; synthesis must refuse.
        bad = list(fixture_corpus)
        other_corpus = hashlib.sha256(b"different-snapshot").hexdigest()
        bad[0] = _input_note(
            skill_id=bad[0].skill_id,
            claim=bad[0].claim,
            quotes=bad[0].exact_quotes,
            confidence=bad[0].confidence,
            why_relevant=bad[0].why_relevant,
            corpus=other_corpus,
        )
        with pytest.raises(AssertionError):
            _expected_synthesis(tuple(bad))

    def test_dedupes_quotes_referenced_by_multiple_inputs(self) -> None:
        shared = _quote(
            "Banca Intesa transferred 120,000 EUR",
            doc_id="doc-A",
            page=2,
            char_offset_start=58,
            char_offset_end=94,
        )
        n1 = _input_note(
            skill_id="find-money-flow@v1",
            claim="A",
            quotes=(shared,),
            confidence=0.9,
            why_relevant="x",
        )
        n2 = _input_note(
            skill_id="summarize-by-entity@v1",
            claim="B",
            quotes=(shared,),
            confidence=0.8,
            why_relevant="y",
        )
        out = _expected_synthesis((n1, n2))
        assert len(out.exact_quotes) == 1


class TestSchemaInvariantsHonoured:
    """Negative cases the synthesis output must continue to reject."""

    def test_zero_quotes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Note(
                claim="empty narrative",
                exact_quotes=(),
                confidence=0.5,
                why_relevant="x",
                source_corpus_snapshot_hash=_CORPUS,
                brief_hash=_BRIEF,
                skill_id=_SKILL_ID,
                skill_resolver_match=_SKILL_RESOLVER_MATCH,
                skill_version=_GIT_SHA,
            )


# ---------------------------------------------------------------------------
# Live-LLM eval — narrative-quality judgement against a real endpoint.
# Skipped without LLM_* env vars; will be wired in when the harness exposes
# a `synthesize_via_skill(skill_id, inputs, brief)` surface (post-v2 starter).
# ---------------------------------------------------------------------------

_REQUIRED_ENV = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")


@pytest.mark.integration
@pytest.mark.skipif(
    not all(k in os.environ for k in _REQUIRED_ENV),
    reason=(
        "Set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL to run the live narrative "
        "quality eval for narrate-fraud-pattern."
    ),
)
def test_live_llm_eval_pending_runtime(fixture_corpus: tuple[Note, ...]) -> None:
    pytest.skip(
        "narrate-fraud-pattern@v1 ships as methodology + contract spec; the "
        "harness skill-routing surface that turns SKILL.md + input notes into "
        "an LLM-driven synthesis call is wired in a follow-up PR. Until then "
        "the live narrative-quality eval has nothing to dispatch against."
    )
