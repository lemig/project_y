"""Brief model + canonical hash tests."""

from __future__ import annotations

import unicodedata

import pytest
from pydantic import ValidationError

from schema.brief import Brief

_GOOD_HASH = "a" * 64


def test_brief_round_trip() -> None:
    b = Brief(text="trace the money", corpus_snapshot_hash=_GOOD_HASH)
    assert Brief(**b.model_dump()) == b


def test_brief_hash_is_stable() -> None:
    b1 = Brief(text="trace the money", corpus_snapshot_hash=_GOOD_HASH)
    b2 = Brief(text="trace the money", corpus_snapshot_hash=_GOOD_HASH)
    assert b1.compute_hash() == b2.compute_hash()


def test_brief_hash_changes_with_text() -> None:
    b1 = Brief(text="trace the money", corpus_snapshot_hash=_GOOD_HASH)
    b2 = Brief(text="trace the funds", corpus_snapshot_hash=_GOOD_HASH)
    assert b1.compute_hash() != b2.compute_hash()


def test_brief_hash_changes_with_corpus() -> None:
    b1 = Brief(text="trace the money", corpus_snapshot_hash=_GOOD_HASH)
    b2 = Brief(text="trace the money", corpus_snapshot_hash="b" * 64)
    assert b1.compute_hash() != b2.compute_hash()


def test_brief_hash_unicode_canonical_nfc_vs_nfd() -> None:
    nfc = "café"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd  # bytes differ
    b_nfc = Brief(text=nfc, corpus_snapshot_hash=_GOOD_HASH)
    b_nfd = Brief(text=nfd, corpus_snapshot_hash=_GOOD_HASH)
    # Stored text is NFC-normalized on input
    assert b_nfc.text == b_nfd.text == nfc
    # And the hashes match — joins survive copy-paste / OCR drift
    assert b_nfc.compute_hash() == b_nfd.compute_hash()


def test_brief_hash_unicode_canonical_realistic() -> None:
    # Romanian: ț (U+021B) vs t + combining cedilla — same look, different bytes
    nfc = "tranzacție bancară"
    nfd = unicodedata.normalize("NFD", nfc)
    b1 = Brief(text=nfc, corpus_snapshot_hash=_GOOD_HASH)
    b2 = Brief(text=nfd, corpus_snapshot_hash=_GOOD_HASH)
    assert b1.compute_hash() == b2.compute_hash()


def test_corpus_hash_validated() -> None:
    with pytest.raises(ValidationError):
        Brief(text="x", corpus_snapshot_hash="not-a-sha")


def test_locale_validated() -> None:
    with pytest.raises(ValidationError):
        Brief(text="x", corpus_snapshot_hash=_GOOD_HASH, locale="EN")
    with pytest.raises(ValidationError):
        Brief(text="x", corpus_snapshot_hash=_GOOD_HASH, locale="eng")


def test_brief_frozen() -> None:
    b = Brief(text="x", corpus_snapshot_hash=_GOOD_HASH)
    with pytest.raises(ValidationError):
        b.text = "y"  # type: ignore[misc]


def test_brief_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        Brief(text="x", corpus_snapshot_hash=_GOOD_HASH, foo="bar")  # type: ignore[call-arg]
