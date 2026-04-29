"""DocumentSource — the canonical Protocol the substring quote verifier reads through.

Workspace C's verifier (``src/verifier/substring.py``) was already merged with a
local stub at ``src/verifier/document_source.py`` waiting for this canonical
implementation to land. The contract there is the contract here: same method
signature, same exception hierarchy. Once this PR merges, the verifier swaps
``from verifier.document_source`` to ``from aleph.document_source`` — no
behavior change.

The verifier is the trust gate. It expects:

* ``get_text(doc_id, page=None) -> str`` — raw text bytes the Quote was
  authored against. The verifier handles NFC normalization and sha256 itself;
  sources don't need to.
* :class:`DocumentNotFound` for a permanently-missing document — translates
  to ``VerificationResult.FAIL_DOC_NOT_FOUND`` (no retry).
* :class:`PageNotFound` for "doc exists but this page doesn't" — translates
  to ``VerificationResult.FAIL_PAGE_NOT_FOUND`` (no retry).
* :class:`TransientSourceError` for retryable infrastructure failures
  (network blip, rate limit, 5xx). The verifier's retry wrapper handles these.

:class:`AlephDocumentSource` adapts :class:`AlephClient` to this Protocol,
translating its HTTP-shaped exceptions into the verifier's domain exceptions.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from aleph.client import (
    AlephClient,
    AlephTransportError,
    NotFoundError,
    RateLimitError,
    ServerError,
)


class DocumentNotFound(Exception):
    """The source does not have a document with this id."""


class PageNotFound(Exception):
    """The document exists but does not contain the requested page."""


class TransientSourceError(Exception):
    """Source signaled a retryable failure (network blip, timeout, 5xx, 429).

    Determinate failures (missing doc, missing page) use the dedicated
    exceptions above and translate to enum results — they are NOT retried.
    """


@runtime_checkable
class DocumentSource(Protocol):
    """Returns NFC-normalizable text for a (doc_id, page) pair.

    ``page=None`` means "the whole document"; offsets in the resulting Quote
    are positions in that text. ``page=N`` means "page N only"; offsets are
    positions in the page's text. Implementations MUST keep the page/doc
    convention stable so ``normalized_text_sha256`` lines up.
    """

    def get_text(self, doc_id: str, page: int | None = None) -> str: ...


class AlephDocumentSource:
    """Adapt :class:`AlephClient` to the :class:`DocumentSource` Protocol.

    Translates AlephClient's HTTP-shaped exceptions into the verifier's
    domain exceptions:

    * :class:`NotFoundError` → :class:`DocumentNotFound` or :class:`PageNotFound`
      (disambiguated by an explicit doc-existence probe when ``page`` is set).
    * :class:`RateLimitError`, :class:`ServerError`, :class:`AlephTransportError`
      → :class:`TransientSourceError` (retryable).
    * Other client errors propagate as-is (caller's bug, not source state).
    """

    def __init__(self, client: AlephClient) -> None:
        self._client = client

    def get_text(self, doc_id: str, page: int | None = None) -> str:
        # Page lookups need to disambiguate "doc missing" from "page missing"
        # so the verifier can route to the right enum result. The full-doc
        # path doesn't need this — get_document_text(page=None) already
        # confirms doc existence via get_entity internally.
        if page is not None:
            try:
                self._client.get_entity(doc_id)
            except NotFoundError as exc:
                raise DocumentNotFound(str(exc)) from exc
            except (RateLimitError, ServerError, AlephTransportError) as exc:
                raise TransientSourceError(str(exc)) from exc

        try:
            doc_text = self._client.get_document_text(doc_id, page=page)
        except NotFoundError as exc:
            if page is None:
                raise DocumentNotFound(str(exc)) from exc
            # page=N path: the doc-existence probe above already passed, so
            # a NotFoundError here means the page itself is missing.
            raise PageNotFound(str(exc)) from exc
        except (RateLimitError, ServerError, AlephTransportError) as exc:
            raise TransientSourceError(str(exc)) from exc
        return doc_text.text
