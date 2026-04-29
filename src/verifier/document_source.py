"""DocumentSource Protocol — local stub for the substring verifier.

Workspace B owns the canonical implementation at ``src/aleph/document_source.py``
(an Aleph REST client). Until that lands, the verifier depends on this minimal
Protocol so tests can drive it with in-memory fakes. When workspace B merges,
swap the import; the contract here is the contract there.

The verifier is the trust gate: it must read NFC-normalized document text and
position-addressable slices. Sources promise to return the same text bytes that
were used to compute ``Quote.normalized_text_sha256``. Sources that cannot keep
that promise (network blip, cache miss in flight) raise ``TransientSourceError``
so the retry wrapper can try again.
"""

from __future__ import annotations

from typing import Protocol


class DocumentNotFound(Exception):
    """The source does not have a document with this id."""


class PageNotFound(Exception):
    """The document exists but does not contain the requested page."""


class TransientSourceError(Exception):
    """Source signaled a retryable failure (network blip, timeout, etc.).

    Determinate failures (missing doc, missing page) use the dedicated
    exceptions above and translate to enum results — they are NOT retried.
    """


class DocumentSource(Protocol):
    """Returns NFC-normalized text for a (doc_id, page) pair.

    ``page=None`` means "the whole document"; offsets in the resulting Quote
    are positions in that text. ``page=N`` means "page N only"; offsets are
    positions in the page's text. Implementations MUST keep the page/doc
    convention stable so ``normalized_text_sha256`` lines up.
    """

    def get_text(self, doc_id: str, page: int | None = None) -> str: ...
