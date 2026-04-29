"""Integration test for summarize-by-entity against a fixture corpus.

This is the v2 starter scaffold for the skill's integration / LLM eval.
The full end-to-end run requires three components that this PR explicitly
does NOT build (per task scope): the substring quote verifier, the Aleph
REST client wrapper, and the harness adapter that loads + dispatches
skills. Those land in sibling PRs.

What this test DOES verify, deterministically and offline:

1. The fixture corpus parses, and every "Acme Holdings Ltd" mention's
   span — `(doc_id, char_offset_start, char_offset_end, source_lang)` —
   is computed by the test itself from the file content. This is what the
   substring verifier will check at run time; we check it here without
   the verifier.
2. The expected `Note` shape — one note per canonical entity, ordered
   chronologically by document date, with multilingual provenance — is
   constructable under the locked `schema.note.Note` model.
3. The non-EN quote carries `quote_text_en` + `translator_of_record`, and
   a translation-failure variant constructs cleanly with the required
   `:translation_failed` exact-suffix marker (CLAUDE.md §5: no silent
   loss).

Once the verifier + harness land, this file gains a real LLM-driven run
that asserts the harness's output equals the golden Note constructed
here. The current shape is deliberately the harness's *target*.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from schema.note import Note, Quote


ENTITY_QUERY = "Acme Holdings Ltd"

# Stable fake hashes for fields the test owns deterministically. The real
# corpus_snapshot_hash comes from `aleph.snapshot.snapshot_collection` at
# run time; the real brief_hash comes from `Brief.compute_hash`. We mint
# placeholders here so the schema validation exercises the right shape.
_CORPUS_SNAPSHOT_HASH = hashlib.sha256(b"summarize-by-entity:fixture").hexdigest()
_BRIEF_HASH = hashlib.sha256(
    f"summarize what we know about {ENTITY_QUERY}".encode("utf-8")
).hexdigest()
_SKILL_VERSION = hashlib.sha1(b"summarize-by-entity@v1:test").hexdigest()
_EXTRACTOR = "fixture-text-1.0@inline"
_TRANSLATOR = "argos-translate-1.9.6@deterministic-eval"


@dataclass(frozen=True)
class FixtureDoc:
    doc_id: str
    path: Path
    source_lang: str
    doc_date: date  # used to assert chronological ordering


def _doc(name: str, fixtures_dir: Path, lang: str, doc_date: date) -> FixtureDoc:
    return FixtureDoc(
        doc_id=name,
        path=fixtures_dir / f"{name}.txt",
        source_lang=lang,
        doc_date=doc_date,
    )


@pytest.fixture(scope="module")
def corpus(request) -> list[FixtureDoc]:
    fixtures_dir = Path(request.path).parent / "fixtures"
    return [
        _doc("doc-001-en-contract", fixtures_dir, "en", date(2024, 3, 14)),
        _doc("doc-002-it-filing", fixtures_dir, "it", date(2024, 4, 2)),
        _doc("doc-003-en-wire", fixtures_dir, "en", date(2024, 5, 22)),
    ]


def _sha256_of(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _quote_for(doc: FixtureDoc, *, quote_text_en: str | None) -> Quote:
    """Build a Quote from the FIRST occurrence of ENTITY_QUERY in the doc.

    Mirrors what the substring verifier will eventually check at run
    time: that `quote_text == doc_text[char_offset_start:char_offset_end]`
    and that `normalized_text_sha256 == sha256(doc_text)`.
    """
    text = doc.path.read_text(encoding="utf-8")
    start = text.find(ENTITY_QUERY)
    assert start != -1, f"{doc.doc_id}: fixture must mention {ENTITY_QUERY!r}"
    end = start + len(ENTITY_QUERY)
    assert text[start:end] == ENTITY_QUERY  # local guard

    is_en = doc.source_lang == "en"
    return Quote(
        quote_text=ENTITY_QUERY,
        quote_text_en=None if is_en else quote_text_en,
        doc_id=doc.doc_id,
        page=1,
        char_offset_start=start,
        char_offset_end=end,
        extractor_version=_EXTRACTOR,
        normalized_text_sha256=_sha256_of(text),
        source_lang=doc.source_lang,
        translator_of_record=None if is_en else _TRANSLATOR,
    )


class TestFixtureCorpus:
    """Sanity-check the fixture corpus itself before depending on it."""

    def test_every_fixture_mentions_the_entity(self, corpus: list[FixtureDoc]) -> None:
        for doc in corpus:
            text = doc.path.read_text(encoding="utf-8")
            assert ENTITY_QUERY in text, (
                f"{doc.doc_id}: fixture must contain {ENTITY_QUERY!r} for the "
                "skill to have anything to summarise"
            )

    def test_corpus_is_multilingual(self, corpus: list[FixtureDoc]) -> None:
        # Per CLAUDE.md §6: ~80% of OLAF cases are non-English. The
        # fixture must include at least one non-EN doc so the skill's
        # multilingual provenance pattern is exercised here.
        langs = {d.source_lang for d in corpus}
        assert "en" in langs and len(langs) >= 2

    def test_doc_dates_are_distinct_and_orderable(self, corpus: list[FixtureDoc]) -> None:
        # Chronological ordering is part of the skill's output contract.
        dates = [d.doc_date for d in corpus]
        assert len(set(dates)) == len(dates), "fixture dates must be distinct"


class TestExpectedNoteShape:
    """Construct the Note the skill is *supposed* to emit on this corpus,
    and validate it against the locked schema. This is the harness's
    target — when the harness adapter lands, its real output is asserted
    equal to a Note built from these same primitives.
    """

    def test_one_note_per_canonical_entity(self, corpus: list[FixtureDoc]) -> None:
        ordered = sorted(corpus, key=lambda d: d.doc_date)
        quotes = tuple(
            _quote_for(
                d,
                quote_text_en=ENTITY_QUERY if d.source_lang != "en" else None,
            )
            for d in ordered
        )
        note = Note(
            claim=(
                f"Entity timeline for {ENTITY_QUERY}: "
                f"{len(quotes)} mention(s) across {len(quotes)} document(s), "
                f"{ordered[0].doc_date.isoformat()}..{ordered[-1].doc_date.isoformat()}"
            ),
            exact_quotes=quotes,
            confidence=min(1.0, 0.4 + 0.1 * len(quotes)),
            why_relevant=(
                "Acme Holdings Ltd appears as: contract counterparty (doc-001), "
                "subject of a chamber-of-commerce filing (doc-002), and wire "
                "beneficiary (doc-003). 0 omitted by salience truncation."
            ),
            source_corpus_snapshot_hash=_CORPUS_SNAPSHOT_HASH,
            brief_hash=_BRIEF_HASH,
            skill_id="summarize-by-entity@v1",
            skill_resolver_match="summarize what we know about",
            skill_version=_SKILL_VERSION,
        )
        assert len(note.exact_quotes) == len(corpus)

    def test_quotes_carry_chronological_order(self, corpus: list[FixtureDoc]) -> None:
        ordered = sorted(corpus, key=lambda d: d.doc_date)
        quotes = tuple(
            _quote_for(
                d,
                quote_text_en=ENTITY_QUERY if d.source_lang != "en" else None,
            )
            for d in ordered
        )
        # The skill orders mentions by doc_date; we assert the resulting
        # quote tuple's doc_id sequence matches the date sequence.
        assert [q.doc_id for q in quotes] == [d.doc_id for d in ordered]

    def test_non_english_quote_carries_translation(
        self, corpus: list[FixtureDoc]
    ) -> None:
        it_doc = next(d for d in corpus if d.source_lang == "it")
        q = _quote_for(it_doc, quote_text_en=ENTITY_QUERY)
        assert q.source_lang == "it"
        assert q.quote_text_en == ENTITY_QUERY
        assert q.translator_of_record == _TRANSLATOR

    def test_translation_failure_marker_path_is_constructable(
        self, corpus: list[FixtureDoc]
    ) -> None:
        # When the translator pipeline fails, CLAUDE.md §5 requires we
        # keep the source quote and mark the failure rather than drop
        # the note. Confirm that pathway constructs cleanly under the
        # locked schema (the marker requires the EXACT
        # ':translation_failed' suffix with a non-empty translator-id
        # prefix — see schema.note._is_translation_failure_marker).
        it_doc = next(d for d in corpus if d.source_lang == "it")
        text = it_doc.path.read_text(encoding="utf-8")
        start = text.find(ENTITY_QUERY)
        end = start + len(ENTITY_QUERY)
        q = Quote(
            quote_text=ENTITY_QUERY,
            quote_text_en=None,
            doc_id=it_doc.doc_id,
            page=1,
            char_offset_start=start,
            char_offset_end=end,
            extractor_version=_EXTRACTOR,
            normalized_text_sha256=_sha256_of(text),
            source_lang="it",
            translator_of_record="argos-translate-1.9.6:translation_failed",
        )
        assert q.quote_text_en is None
        assert q.translator_of_record.endswith(":translation_failed")

    def test_substring_invariant_holds_for_every_quote(
        self, corpus: list[FixtureDoc]
    ) -> None:
        # Pre-flight what the substring verifier (deterministic Python,
        # not in this PR) will check at run time:
        #   doc_text[char_offset_start:char_offset_end] == quote_text
        # This is the audit trail's load-bearing invariant; the schema
        # cannot enforce it (no document at validation time, see
        # schema/note.py docstring), so the test asserts it directly
        # against the fixture files.
        for doc in corpus:
            text = doc.path.read_text(encoding="utf-8")
            q = _quote_for(
                doc,
                quote_text_en=ENTITY_QUERY if doc.source_lang != "en" else None,
            )
            assert text[q.char_offset_start : q.char_offset_end] == q.quote_text


@pytest.mark.skip(
    reason=(
        "End-to-end LLM-driven run is gated on the verifier + harness "
        "adapter + REST client landing in sibling PRs (per task scope: "
        "'Do NOT build the verifier, the REST client, or the harness "
        "adapter'). When those land, this test runs the harness against "
        "the fixture corpus and asserts the emitted Note tuple equals "
        "the one TestExpectedNoteShape constructs above."
    )
)
def test_end_to_end_skill_run_produces_expected_notes() -> None:
    raise NotImplementedError
