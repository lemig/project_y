"""DocumentSource — the narrow surface the substring quote verifier depends on.

The substring quote verifier (workspace C) is a deterministic, pure-Python
generation-time gate. It must NOT take a hard dependency on the concrete
:class:`AlephClient`: tests need to substitute fixtures, alternate substrates
(filesystem, manifest snapshots) need to plug in, and replay tests need a
deterministic surface. So the verifier reads through this Protocol.

:class:`AlephDocumentSource` adapts the REST client to the Protocol. It is
the only adapter we ship in v2 — additional sources land alongside the
manifest+hash corpus snapshot fallback (architectural premise #8).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from aleph.client import AlephClient, DocumentText


@runtime_checkable
class DocumentSource(Protocol):
    """Narrow surface required by the substring quote verifier.

    Implementations promise: given ``(doc_id, page)``, return the exact
    NFC-normalized text the verifier should substring-search, plus the
    sha256 hash of that text and the extractor version that produced it.
    Implementations that cannot satisfy the request must raise
    :class:`aleph.client.NotFoundError` rather than returning empty text —
    silent loss is unacceptable per CLAUDE.md.
    """

    def get_document_text(
        self, doc_id: str, *, page: int | None = None
    ) -> DocumentText: ...


class AlephDocumentSource:
    """Adapt :class:`AlephClient` to the :class:`DocumentSource` Protocol."""

    def __init__(self, client: AlephClient) -> None:
        self._client = client

    def get_document_text(
        self, doc_id: str, *, page: int | None = None
    ) -> DocumentText:
        return self._client.get_document_text(doc_id, page=page)
