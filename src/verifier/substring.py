"""Substring quote verifier — the deterministic trust gate.

Per CLAUDE.md, this is a HARD generation-time gate: every Quote produced by a
skill must round-trip against the document text it claims to come from. Two
checks, both pure-Python and side-effect-free apart from reading the source:

1. ``normalized_text_sha256`` matches sha256(NFC(doc_text)) — proves the
   verifier is looking at the same bytes the Quote was authored against.
2. ``doc_text[char_offset_start:char_offset_end] == NFC(quote_text)`` — proves
   the offsets address the claimed text verbatim.

Failure surfaces as a ``VerificationResult`` enum, never an exception, so the
caller can route to the audit log without an ``except Exception:`` (banned).
Transient infrastructure errors raised by the source DO propagate so the retry
wrapper can handle them without conflating "missing doc" with "network blip".
"""

from __future__ import annotations

import hashlib
import unicodedata
from enum import Enum

from schema.note import Quote
from verifier.document_source import (
    DocumentNotFound,
    DocumentSource,
    PageNotFound,
    TransientSourceError,
)


class VerificationResult(str, Enum):
    PASS = "pass"
    FAIL_QUOTE_MISMATCH = "fail_quote_mismatch"
    FAIL_HASH_MISMATCH = "fail_hash_mismatch"
    FAIL_DOC_NOT_FOUND = "fail_doc_not_found"
    FAIL_PAGE_NOT_FOUND = "fail_page_not_found"


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_quote(quote: Quote, source: DocumentSource) -> VerificationResult:
    try:
        raw = source.get_text(quote.doc_id, page=quote.page)
    except DocumentNotFound:
        return VerificationResult.FAIL_DOC_NOT_FOUND
    except PageNotFound:
        return VerificationResult.FAIL_PAGE_NOT_FOUND

    text = _nfc(raw)
    if _sha256(text) != quote.normalized_text_sha256:
        return VerificationResult.FAIL_HASH_MISMATCH

    expected = _nfc(quote.quote_text)
    if quote.char_offset_end > len(text):
        return VerificationResult.FAIL_QUOTE_MISMATCH
    if text[quote.char_offset_start : quote.char_offset_end] != expected:
        return VerificationResult.FAIL_QUOTE_MISMATCH

    return VerificationResult.PASS


def verify_quote_with_retry(
    quote: Quote,
    source: DocumentSource,
    *,
    max_retries: int = 3,
) -> VerificationResult:
    """Retry verification on transient source errors only.

    Determinate results (PASS or any FAIL_*) return immediately. Per CLAUDE.md
    the verifier is the trust gate — retrying a FAIL_QUOTE_MISMATCH cannot
    flip it to PASS deterministically, so retries are reserved for transient
    infrastructure errors. After ``max_retries`` transient failures, the last
    ``TransientSourceError`` is re-raised so the caller can drop+log.
    """
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")

    last_err: TransientSourceError | None = None
    for _ in range(max_retries):
        try:
            return verify_quote(quote, source)
        except TransientSourceError as exc:
            last_err = exc
    assert last_err is not None
    raise last_err
