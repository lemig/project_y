"""Round-trip + invariant tests for the v2 Note/Quote schema.

These are the locked contract. Changing them requires a deliberate schema
migration + golden-run replay regen.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from schema.note import Note, Quote


def _sha(seed: bytes = b"x") -> str:
    return hashlib.sha256(seed).hexdigest()


def _git_sha(seed: bytes = b"skill") -> str:
    return hashlib.sha1(seed).hexdigest()  # 40-char hex, matches git SHA-1 shape


def _good_quote(**overrides: Any) -> Quote:
    base: dict[str, Any] = dict(
        quote_text="Banca Intesa transferred 120,000 EUR",
        quote_text_en=None,
        doc_id="doc-42",
        page=3,
        char_offset_start=128,
        char_offset_end=164,
        extractor_version="tesseract-5.3.1@aleph-3.18",
        normalized_text_sha256=_sha(),
        source_lang="en",
        translator_of_record=None,
    )
    base.update(overrides)
    return Quote(**base)


def _good_note(**overrides: Any) -> Note:
    base: dict[str, Any] = dict(
        claim="120k flowed from A to B on 2024-03-12",
        exact_quotes=(_good_quote(),),
        confidence=0.85,
        why_relevant="Establishes the contested transfer.",
        source_corpus_snapshot_hash=_sha(b"corpus"),
        brief_hash=_sha(b"brief"),
        skill_id="find-money-flow@v1",
        skill_resolver_match="money flow",
        skill_version=_git_sha(),
    )
    base.update(overrides)
    return Note(**base)


class TestQuote:
    def test_round_trip(self) -> None:
        q = _good_quote()
        assert Quote(**q.model_dump()) == q

    def test_offset_invariant_end_must_exceed_start(self) -> None:
        with pytest.raises(ValidationError):
            _good_quote(char_offset_start=200, char_offset_end=100)
        with pytest.raises(ValidationError):
            _good_quote(char_offset_start=100, char_offset_end=100)

    def test_negative_offset_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _good_quote(char_offset_start=-1, char_offset_end=10)

    def test_zero_page_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _good_quote(page=0)

    def test_none_page_allowed(self) -> None:
        q = _good_quote(page=None)
        assert q.page is None

    def test_sha256_format_strict(self) -> None:
        with pytest.raises(ValidationError):
            _good_quote(normalized_text_sha256="not-a-sha")
        with pytest.raises(ValidationError):
            _good_quote(normalized_text_sha256="ABCDEF" + "0" * 58)
        with pytest.raises(ValidationError):
            _good_quote(normalized_text_sha256="0" * 63)

    def test_iso_lang_format(self) -> None:
        with pytest.raises(ValidationError):
            _good_quote(source_lang="EN")
        with pytest.raises(ValidationError):
            _good_quote(source_lang="eng")
        with pytest.raises(ValidationError):
            _good_quote(source_lang="e")

    def test_english_source_forbids_translation_fields(self) -> None:
        with pytest.raises(ValidationError):
            _good_quote(source_lang="en", quote_text_en="something", translator_of_record="x:y")
        with pytest.raises(ValidationError):
            _good_quote(source_lang="en", translator_of_record="argos-1.9")

    def test_non_english_requires_translator_of_record(self) -> None:
        with pytest.raises(ValidationError):
            _good_quote(
                source_lang="it",
                quote_text="Banca Intesa ha trasferito 120.000 EUR",
                quote_text_en="Banca Intesa transferred 120,000 EUR",
                translator_of_record=None,
            )

    def test_translation_failure_marker_allowed(self) -> None:
        q = _good_quote(
            source_lang="it",
            quote_text="Banca Intesa ha trasferito 120.000 EUR",
            quote_text_en=None,
            translator_of_record="argos-1.9:translation_failed",
        )
        assert q.quote_text_en is None

    def test_non_english_dropped_translation_without_marker_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _good_quote(
                source_lang="it",
                quote_text="Banca Intesa ha trasferito 120.000 EUR",
                quote_text_en=None,
                translator_of_record="argos-1.9",
            )

    def test_forged_failure_marker_rejected(self) -> None:
        # Substring forgery: marker not at the end
        with pytest.raises(ValidationError):
            _good_quote(
                source_lang="it",
                quote_text="x",
                quote_text_en=None,
                translator_of_record="argos:translation_failed-but-not-really",
            )
        # Bare suffix with no translator-id prefix
        with pytest.raises(ValidationError):
            _good_quote(
                source_lang="it",
                quote_text="x",
                quote_text_en=None,
                translator_of_record=":translation_failed",
            )
        # Trailing junk after marker
        with pytest.raises(ValidationError):
            _good_quote(
                source_lang="it",
                quote_text="x",
                quote_text_en=None,
                translator_of_record="argos:translation_failed\x00junk",
            )

    def test_failure_marker_with_translation_text_rejected(self) -> None:
        # Mutually exclusive: cannot claim failure AND provide translation
        with pytest.raises(ValidationError):
            _good_quote(
                source_lang="it",
                quote_text="x",
                quote_text_en="some translation",
                translator_of_record="argos-1.9:translation_failed",
            )

    def test_empty_translation_strings_rejected(self) -> None:
        # Empty quote_text_en
        with pytest.raises(ValidationError):
            _good_quote(
                source_lang="it",
                quote_text="x",
                quote_text_en="",
                translator_of_record="argos-1.9",
            )
        # Empty translator_of_record
        with pytest.raises(ValidationError):
            _good_quote(
                source_lang="it",
                quote_text="x",
                quote_text_en="x",
                translator_of_record="",
            )

    def test_whitespace_only_translation_strings_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _good_quote(
                source_lang="it",
                quote_text="x",
                quote_text_en="   ",
                translator_of_record="argos-1.9",
            )
        with pytest.raises(ValidationError):
            _good_quote(
                source_lang="it",
                quote_text="x",
                quote_text_en="x",
                translator_of_record="\t\n",
            )

    def test_whitespace_prefix_failure_marker_rejected(self) -> None:
        # ' :translation_failed' must NOT count as a valid failure marker
        with pytest.raises(ValidationError):
            _good_quote(
                source_lang="it",
                quote_text="x",
                quote_text_en=None,
                translator_of_record=" :translation_failed",
            )

    def test_frozen_blocks_assignment(self) -> None:
        q = _good_quote()
        with pytest.raises(ValidationError):
            q.quote_text = "different"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        payload = _good_quote().model_dump()
        payload["extra_field"] = "nope"
        with pytest.raises(ValidationError):
            Quote(**payload)


class TestNote:
    def test_round_trip(self) -> None:
        n = _good_note()
        assert Note(**n.model_dump()) == n

    def test_at_least_one_quote_required(self) -> None:
        with pytest.raises(ValidationError):
            _good_note(exact_quotes=())

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            _good_note(confidence=-0.1)
        with pytest.raises(ValidationError):
            _good_note(confidence=1.1)
        assert _good_note(confidence=0.0).confidence == 0.0
        assert _good_note(confidence=1.0).confidence == 1.0

    def test_tier_default_is_investigation(self) -> None:
        assert _good_note().tier == "investigation"

    def test_mandate_tier_rejected_in_v2(self) -> None:
        with pytest.raises(ValidationError):
            _good_note(tier="mandate")

    def test_brief_and_corpus_hashes_validated(self) -> None:
        with pytest.raises(ValidationError):
            _good_note(brief_hash="not-a-sha")
        with pytest.raises(ValidationError):
            _good_note(source_corpus_snapshot_hash="A" * 64)

    def test_skill_version_must_be_40_hex_git_sha(self) -> None:
        with pytest.raises(ValidationError):
            _good_note(skill_version="abc1234")  # too short
        with pytest.raises(ValidationError):
            _good_note(skill_version="A" * 40)  # uppercase
        with pytest.raises(ValidationError):
            _good_note(skill_version="z" * 40)  # non-hex
        # 40-char lowercase hex passes
        assert _good_note(skill_version=_git_sha(b"other")).skill_version == _git_sha(b"other")

    def test_extra_fields_forbidden(self) -> None:
        payload = _good_note().model_dump()
        payload["foo"] = "bar"
        with pytest.raises(ValidationError):
            Note(**payload)

    def test_frozen_blocks_assignment(self) -> None:
        n = _good_note()
        with pytest.raises(ValidationError):
            n.claim = "different"  # type: ignore[misc]

    def test_multiple_quotes_supported(self) -> None:
        n = _good_note(
            exact_quotes=(
                _good_quote(),
                _good_quote(doc_id="doc-43", char_offset_start=10, char_offset_end=42),
            )
        )
        assert len(n.exact_quotes) == 2
