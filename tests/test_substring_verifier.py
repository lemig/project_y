"""Trust-gate tests for the substring quote verifier.

These pin the contract from CLAUDE.md: every Quote round-trips against the
document text it claims to come from, NFC-normalized, with hash + offset
agreement. Failures are enumerated; transient errors retry; deterministic
errors do not.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Any

import pytest

from schema.note import Quote
from verifier.document_source import (
    DocumentNotFound,
    PageNotFound,
    TransientSourceError,
)
from verifier.substring import (
    VerificationResult,
    verify_quote,
    verify_quote_with_retry,
)


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _sha(text: str) -> str:
    return hashlib.sha256(_nfc(text).encode("utf-8")).hexdigest()


DOC_TEXT_EN = (
    "Memo dated 2024-03-12. Banca Intesa transferred 120,000 EUR "
    "to ACME Holdings on 2024-03-12, per wire instructions filed "
    "under reference R-7741."
)
QUOTE_EN = "Banca Intesa transferred 120,000 EUR"
START_EN = DOC_TEXT_EN.index(QUOTE_EN)
END_EN = START_EN + len(QUOTE_EN)


def _quote_en(**overrides: Any) -> Quote:
    base: dict[str, Any] = dict(
        quote_text=QUOTE_EN,
        quote_text_en=None,
        doc_id="doc-42",
        page=None,
        char_offset_start=START_EN,
        char_offset_end=END_EN,
        extractor_version="tesseract-5.3.1@aleph-3.18",
        normalized_text_sha256=_sha(DOC_TEXT_EN),
        source_lang="en",
        translator_of_record=None,
    )
    base.update(overrides)
    return Quote(**base)


class FakeSource:
    """In-memory DocumentSource for tests.

    docs: ``{doc_id: {None: full_text, 1: page1_text, ...}}``.
    """

    def __init__(self, docs: dict[str, dict[int | None, str]]) -> None:
        self.docs = docs
        self.calls: list[tuple[str, int | None]] = []

    def get_text(self, doc_id: str, page: int | None = None) -> str:
        self.calls.append((doc_id, page))
        if doc_id not in self.docs:
            raise DocumentNotFound(doc_id)
        pages = self.docs[doc_id]
        if page not in pages:
            raise PageNotFound(f"{doc_id} page {page}")
        return pages[page]


class FlakySource:
    """Raises TransientSourceError ``fail_n`` times, then delegates."""

    def __init__(self, inner: FakeSource, fail_n: int) -> None:
        self.inner = inner
        self.fail_n = fail_n
        self.attempts = 0

    def get_text(self, doc_id: str, page: int | None = None) -> str:
        self.attempts += 1
        if self.attempts <= self.fail_n:
            raise TransientSourceError(f"flake on attempt {self.attempts}")
        return self.inner.get_text(doc_id, page=page)


@pytest.fixture
def en_source() -> FakeSource:
    return FakeSource({"doc-42": {None: DOC_TEXT_EN}})


class TestVerifyQuoteHappyPath:
    def test_pass_english(self, en_source: FakeSource) -> None:
        assert verify_quote(_quote_en(), en_source) is VerificationResult.PASS

    def test_pass_with_page_addressing(self) -> None:
        page_text = "Pagina 1: " + DOC_TEXT_EN
        src = FakeSource({"doc-42": {1: page_text}})
        start = page_text.index(QUOTE_EN)
        end = start + len(QUOTE_EN)
        q = _quote_en(
            page=1,
            char_offset_start=start,
            char_offset_end=end,
            normalized_text_sha256=_sha(page_text),
        )
        assert verify_quote(q, src) is VerificationResult.PASS

    def test_pass_non_english_with_translation(self) -> None:
        # NFC vs decomposed form: the doc stores composed 'à', the quote too.
        doc = "Banca Intesa ha trasferito 120.000 EUR à ACME"
        quote_text = "Banca Intesa ha trasferito 120.000 EUR à ACME"
        src = FakeSource({"doc-it": {None: doc}})
        q = Quote(
            quote_text=quote_text,
            quote_text_en="Banca Intesa transferred 120,000 EUR to ACME",
            doc_id="doc-it",
            page=None,
            char_offset_start=0,
            char_offset_end=len(quote_text),
            extractor_version="tesseract-5.3.1@aleph-3.18",
            normalized_text_sha256=_sha(doc),
            source_lang="it",
            translator_of_record="argos-1.9",
        )
        assert verify_quote(q, src) is VerificationResult.PASS

    def test_decomposed_quote_normalizes_to_match(self) -> None:
        # Doc is composed; quote arrives decomposed. NFC must reconcile both.
        doc = "café receipt"  # composed é
        decomposed_quote = "café"  # e + combining acute
        src = FakeSource({"doc-fr": {None: doc}})
        composed = _nfc(decomposed_quote)
        q = Quote(
            quote_text=decomposed_quote,
            quote_text_en="cafe",
            doc_id="doc-fr",
            page=None,
            char_offset_start=0,
            char_offset_end=len(composed),
            extractor_version="tesseract-5.3.1@aleph-3.18",
            normalized_text_sha256=_sha(doc),
            source_lang="fr",
            translator_of_record="argos-1.9",
        )
        assert verify_quote(q, src) is VerificationResult.PASS


class TestVerifyQuoteFailures:
    def test_fail_doc_not_found(self) -> None:
        src = FakeSource({})
        assert verify_quote(_quote_en(), src) is VerificationResult.FAIL_DOC_NOT_FOUND

    def test_fail_page_not_found(self) -> None:
        src = FakeSource({"doc-42": {1: "page one only"}})
        q = _quote_en(
            page=2,
            normalized_text_sha256=_sha("doesn't matter"),
        )
        assert verify_quote(q, src) is VerificationResult.FAIL_PAGE_NOT_FOUND

    def test_fail_hash_mismatch_when_doc_text_drifts(
        self, en_source: FakeSource
    ) -> None:
        # Forge a quote against a doc that has been re-extracted (different bytes).
        forged = _quote_en(normalized_text_sha256=_sha("stale doc text"))
        assert verify_quote(forged, en_source) is VerificationResult.FAIL_HASH_MISMATCH

    def test_fail_quote_mismatch_off_by_one_left(self, en_source: FakeSource) -> None:
        q = _quote_en(char_offset_start=START_EN - 1, char_offset_end=END_EN - 1)
        assert verify_quote(q, en_source) is VerificationResult.FAIL_QUOTE_MISMATCH

    def test_fail_quote_mismatch_off_by_one_right(self, en_source: FakeSource) -> None:
        q = _quote_en(char_offset_start=START_EN + 1, char_offset_end=END_EN + 1)
        assert verify_quote(q, en_source) is VerificationResult.FAIL_QUOTE_MISMATCH

    def test_fail_quote_mismatch_text_does_not_match_offsets(
        self, en_source: FakeSource
    ) -> None:
        q = _quote_en(quote_text="ACME Holdings on 2024-03-12")  # real string in doc
        assert verify_quote(q, en_source) is VerificationResult.FAIL_QUOTE_MISMATCH

    def test_fail_quote_mismatch_when_offsets_run_past_end(self) -> None:
        short_doc = "short"
        src = FakeSource({"doc-42": {None: short_doc}})
        q = _quote_en(
            quote_text="short",
            char_offset_start=0,
            char_offset_end=999,
            normalized_text_sha256=_sha(short_doc),
        )
        assert verify_quote(q, src) is VerificationResult.FAIL_QUOTE_MISMATCH

    def test_hash_check_runs_before_offset_check(
        self, en_source: FakeSource
    ) -> None:
        # Both hash and offsets are wrong; verifier must report hash mismatch
        # so the caller knows it was reading drifted bytes, not a forged offset.
        q = _quote_en(
            normalized_text_sha256=_sha("different doc"),
            char_offset_start=999,
            char_offset_end=1000,
        )
        assert verify_quote(q, en_source) is VerificationResult.FAIL_HASH_MISMATCH


class TestRetryWrapper:
    def test_returns_pass_without_retry_when_source_is_healthy(
        self, en_source: FakeSource
    ) -> None:
        result = verify_quote_with_retry(_quote_en(), en_source, max_retries=3)
        assert result is VerificationResult.PASS
        assert len(en_source.calls) == 1

    def test_recovers_after_two_transient_failures(
        self, en_source: FakeSource
    ) -> None:
        flaky = FlakySource(en_source, fail_n=2)
        result = verify_quote_with_retry(_quote_en(), flaky, max_retries=3)
        assert result is VerificationResult.PASS
        assert flaky.attempts == 3

    def test_raises_after_max_retries_exhausted(
        self, en_source: FakeSource
    ) -> None:
        flaky = FlakySource(en_source, fail_n=10)
        with pytest.raises(TransientSourceError):
            verify_quote_with_retry(_quote_en(), flaky, max_retries=3)
        assert flaky.attempts == 3

    def test_determinate_failure_short_circuits_retries(self) -> None:
        # FAIL_QUOTE_MISMATCH must NOT trigger retries — it's deterministic.
        src = FakeSource({"doc-42": {None: DOC_TEXT_EN}})
        q = _quote_en(char_offset_start=START_EN - 1, char_offset_end=END_EN - 1)
        result = verify_quote_with_retry(q, src, max_retries=3)
        assert result is VerificationResult.FAIL_QUOTE_MISMATCH
        assert len(src.calls) == 1

    def test_doc_not_found_short_circuits_retries(self) -> None:
        src = FakeSource({})
        result = verify_quote_with_retry(_quote_en(), src, max_retries=3)
        assert result is VerificationResult.FAIL_DOC_NOT_FOUND
        assert len(src.calls) == 1

    def test_invalid_max_retries_rejected(self, en_source: FakeSource) -> None:
        with pytest.raises(ValueError):
            verify_quote_with_retry(_quote_en(), en_source, max_retries=0)
        with pytest.raises(ValueError):
            verify_quote_with_retry(_quote_en(), en_source, max_retries=-1)
