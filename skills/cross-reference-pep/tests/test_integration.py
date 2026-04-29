"""Integration eval for cross-reference-pep@v1 — placeholder behavior.

The v2 skill is a flag, not a lookup: for every named entity in the
corpus it emits one investigation-tier Note with a verbatim quote and
full provenance. There is no LLM call yet (v3 wires OpenSanctions),
which means this test does NOT run a model — it walks a fixture
corpus, builds the Notes the skill is contracted to produce, and
asserts every Note round-trips through the locked Pydantic schema.

What this catches:
  * silent loss — a mention in the fixture must produce a Note;
  * schema drift — if Note/Quote tightens, this test fails first;
  * multilingual handling — non-English mentions must carry an English
    rendering OR the canonical ``<translator-id>:translation_failed``
    marker (no silent skip);
  * entity-mention quotes are pinned to real character offsets and
    survive the same kind of substring check the verifier will perform
    at runtime.

What this does NOT cover (still v3 work):
  * harness routing of a brief to this skill;
  * a live LLM producing the Notes;
  * the substring quote verifier component.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import pytest

from schema.brief import Brief
from schema.note import Note, Quote
from skills.skill import SkillFrontmatter

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "corpus.json"

_FAKE_CORPUS_HASH = "a" * 64
_FAKE_SKILL_GIT_SHA = "0" * 40

_INTEGRATION_BRIEF = (
    "Verify counterparties Acme Corp, Società Beta S.r.l., and Monsieur Dupont "
    "before approving the contract; also screen director John Doe."
)


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _sha256(s: str) -> str:
    return hashlib.sha256(_nfc(s).encode("utf-8")).hexdigest()


def _build_placeholder_note(
    *,
    doc: dict,
    mention: dict,
    brief: Brief,
    resolver_match: str,
) -> Note:
    """Materialise the Note that cross-reference-pep@v1 contracts to
    emit for one entity mention. Mirrors the SKILL.md "Skill behavior"
    section step-for-step. Pure construction — no LLM, no harness."""

    text = doc["text"]
    start, end = mention["char_offset_start"], mention["char_offset_end"]
    verbatim = text[start:end]
    # The substring verifier will do this exact check at runtime; if the
    # offsets in the fixture drift, the integration test catches it.
    assert verbatim == mention["entity_name"], (
        f"fixture offsets do not extract entity_name "
        f"(got {verbatim!r}, expected {mention['entity_name']!r})"
    )

    source_lang = doc["source_lang"]
    if source_lang == "en":
        quote_text_en = None
        translator_of_record = None
    else:
        quote_text_en = mention.get("quote_text_en")
        translator_of_record = mention.get("translator_of_record")

    quote = Quote(
        quote_text=verbatim,
        quote_text_en=quote_text_en,
        doc_id=doc["doc_id"],
        page=doc["page"],
        char_offset_start=start,
        char_offset_end=end,
        extractor_version=doc["extractor_version"],
        normalized_text_sha256=_sha256(text),
        source_lang=source_lang,
        translator_of_record=translator_of_record,
    )

    return Note(
        claim=f'Entity "{mention["entity_name"]}" requires PEP / sanctions screening.',
        exact_quotes=(quote,),
        confidence=0.4,
        why_relevant=mention["why_relevant"],
        source_corpus_snapshot_hash=brief.corpus_snapshot_hash,
        brief_hash=brief.compute_hash(),
        skill_id="cross-reference-pep@v1",
        skill_resolver_match=resolver_match,
        skill_version=_FAKE_SKILL_GIT_SHA,
    )


@pytest.fixture(scope="module")
def corpus() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))["documents"]


@pytest.fixture(scope="module")
def brief() -> Brief:
    return Brief(text=_INTEGRATION_BRIEF, corpus_snapshot_hash=_FAKE_CORPUS_HASH)


@pytest.fixture(scope="module")
def resolver_match(skill_frontmatter: dict) -> str:
    fm = SkillFrontmatter(**skill_frontmatter)
    m = re.compile(fm.resolver).search(_INTEGRATION_BRIEF)
    assert m is not None, "resolver must fire on the integration brief"
    return m.group(0)


@pytest.fixture(scope="module")
def notes(corpus: list[dict], brief: Brief, resolver_match: str) -> list[Note]:
    return [
        _build_placeholder_note(
            doc=doc, mention=mention, brief=brief, resolver_match=resolver_match
        )
        for doc in corpus
        for mention in doc["mentions"]
    ]


def test_one_note_per_entity_mention(notes: list[Note], corpus: list[dict]) -> None:
    expected = sum(len(doc["mentions"]) for doc in corpus)
    assert len(notes) == expected
    assert expected >= 4, "fixture must exercise EN + non-EN + translation-failure paths"


def test_every_note_carries_at_least_one_quote(notes: list[Note]) -> None:
    for note in notes:
        assert len(note.exact_quotes) >= 1


def test_every_note_claim_flags_entity_for_screening(notes: list[Note]) -> None:
    for note in notes:
        assert "PEP / sanctions screening" in note.claim


def test_skill_id_and_version_consistent(notes: list[Note]) -> None:
    for note in notes:
        assert note.skill_id == "cross-reference-pep@v1"
        assert re.fullmatch(r"[0-9a-f]{40}", note.skill_version)


def test_brief_hash_is_stable_across_notes(notes: list[Note], brief: Brief) -> None:
    expected = brief.compute_hash()
    for note in notes:
        assert note.brief_hash == expected


def test_quotes_pin_to_real_document_offsets(
    notes: list[Note], corpus: list[dict]
) -> None:
    """Mirror what the substring verifier does: extract the cited slice
    from the cited document and confirm it byte-equals quote_text."""
    by_id = {doc["doc_id"]: doc for doc in corpus}
    for note in notes:
        for q in note.exact_quotes:
            doc = by_id[q.doc_id]
            assert doc["text"][q.char_offset_start : q.char_offset_end] == q.quote_text


def test_normalized_text_sha256_matches_document(
    notes: list[Note], corpus: list[dict]
) -> None:
    by_id = {doc["doc_id"]: doc for doc in corpus}
    for note in notes:
        for q in note.exact_quotes:
            assert q.normalized_text_sha256 == _sha256(by_id[q.doc_id]["text"])


def test_english_quotes_have_no_translator(notes: list[Note]) -> None:
    for note in notes:
        for q in note.exact_quotes:
            if q.source_lang == "en":
                assert q.quote_text_en is None
                assert q.translator_of_record is None


def test_non_english_quotes_record_translator_or_failure(notes: list[Note]) -> None:
    """No silent loss: every non-English quote either carries a
    translation or the canonical translation_failed marker."""
    saw_success = False
    saw_failure = False
    for note in notes:
        for q in note.exact_quotes:
            if q.source_lang == "en":
                continue
            assert q.translator_of_record is not None
            if q.translator_of_record.endswith(":translation_failed"):
                assert q.quote_text_en is None
                saw_failure = True
            else:
                assert q.quote_text_en is not None
                saw_success = True
    assert saw_success, "fixture must exercise the translation-success path"
    assert saw_failure, "fixture must exercise the translation-failure marker"


def test_resolver_match_recorded_on_every_note(
    notes: list[Note], resolver_match: str
) -> None:
    for note in notes:
        assert note.skill_resolver_match == resolver_match
        assert note.skill_resolver_match.strip() != ""
