"""Aleph REST client + DocumentSource protocol tests.

Unit tests use ``httpx.MockTransport`` so the suite runs without a live
Aleph stack. Integration tests are gated behind ``pytest.mark.integration``
and hit the per-workspace dev stack started by ``bin/dev-up``.
"""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from typing import Any

import httpx
import pytest

from aleph.client import (
    AlephClient,
    AlephHTTPError,
    AlephResponseError,
    AlephTransportError,
    AuthenticationError,
    Collection,
    DocumentText,
    Entity,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    SearchResults,
    ServerError,
)
from aleph.document_source import (
    AlephDocumentSource,
    DocumentNotFound,
    DocumentSource,
    PageNotFound,
    TransientSourceError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

API_BASE = "http://aleph.test/api/2"
API_KEY = "test-api-key"


def _make_client(handler, *, extractor_version: str = "tesseract-5.3.1@aleph-3.18") -> AlephClient:
    transport = httpx.MockTransport(handler)
    return AlephClient(
        base_url=API_BASE,
        api_key=API_KEY,
        extractor_version=extractor_version,
        transport=transport,
    )


def _json(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def _sha256_nfc(s: str) -> str:
    return hashlib.sha256(unicodedata.normalize("NFC", s).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------


def test_auth_header_format() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization", "")
        return _json({"results": [], "total": 0, "limit": 50})

    with _make_client(handler) as client:
        client.search("anything")

    assert seen["authorization"] == f"ApiKey {API_KEY}"


def test_constructor_rejects_blank_inputs() -> None:
    with pytest.raises(ValueError):
        AlephClient(base_url="", api_key="k")
    with pytest.raises(ValueError):
        AlephClient(base_url=API_BASE, api_key="")
    with pytest.raises(ValueError):
        AlephClient(base_url=API_BASE, api_key="k", extractor_version="")


def test_base_url_trailing_slash_tolerated() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return _json({"results": [], "total": 0, "limit": 50})

    transport = httpx.MockTransport(handler)
    client = AlephClient(
        base_url=API_BASE + "/", api_key=API_KEY, transport=transport
    )
    client.search("hello")
    assert seen["url"].startswith(f"{API_BASE}/entities")


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_decodes_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/2/entities"
        assert request.url.params["q"] == "fraud"
        assert request.url.params["limit"] == "10"
        assert request.url.params["filter:collection_id"] == "coll-1"
        return _json(
            {
                "results": [
                    {
                        "id": "ent-1",
                        "schema": "Person",
                        "collection_id": "coll-1",
                        "properties": {"name": ["Jane Doe"]},
                    }
                ],
                "total": 1,
                "limit": 10,
                "offset": 0,
                "page": 1,
                "pages": 1,
            }
        )

    with _make_client(handler) as client:
        out = client.search("fraud", collection_id="coll-1", limit=10)

    assert isinstance(out, SearchResults)
    assert out.total == 1
    assert len(out.results) == 1
    ent = out.results[0]
    assert isinstance(ent, Entity)
    assert ent.id == "ent-1"
    assert ent.schema_ == "Person"
    assert ent.properties["name"] == ["Jane Doe"]


def test_search_omits_collection_filter_when_none() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return _json({"results": [], "total": 0, "limit": 50})

    with _make_client(handler) as client:
        client.search("fraud")

    assert "filter:collection_id" not in seen["params"]


def test_search_validates_limit_and_offset() -> None:
    client = AlephClient(
        base_url=API_BASE, api_key=API_KEY, transport=httpx.MockTransport(lambda r: _json({}))
    )
    with pytest.raises(ValueError):
        client.search("x", limit=0)
    with pytest.raises(ValueError):
        client.search("x", offset=-1)


def test_search_rejects_reserved_filter_keys() -> None:
    """``filters={"collection_id": ...}`` must error rather than smuggle a
    second ``filter:collection_id`` past the dedicated kwarg — a snapshot/
    enumeration call site that bypassed the guard could silently widen scope
    across collections."""
    client = AlephClient(
        base_url=API_BASE, api_key=API_KEY, transport=httpx.MockTransport(lambda r: _json({}))
    )
    with pytest.raises(ValueError, match="reserved"):
        client.search("x", filters={"collection_id": "evil"})
    with pytest.raises(ValueError, match="reserved"):
        client.search("x", filters={"schemata": "Document"})


def test_search_forwards_sort_param() -> None:
    """``sort=caption:asc`` is the snapshot's stable-pagination guard. The
    client must put it on the wire as ``?sort=caption:asc`` so Aleph's
    SearchQueryParser picks it up."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["sort"] = request.url.params.get("sort", "")
        return _json({"results": [], "total": 0, "limit": 50})

    with _make_client(handler) as client:
        client.search("", sort="caption:asc")

    assert seen["sort"] == "caption:asc"


def test_search_omits_sort_param_when_none() -> None:
    seen: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = list(request.url.params.keys())
        return _json({"results": [], "total": 0, "limit": 50})

    with _make_client(handler) as client:
        client.search("")

    assert "sort" not in seen["params"]


def test_search_rejects_empty_sort_string() -> None:
    """``sort=""`` would slip an empty value past Aleph and silently fall
    through to default ordering — caller almost certainly meant ``None``."""
    client = _make_client(lambda r: _json({}))
    with pytest.raises(ValueError, match="sort"):
        client.search("x", sort="")


def test_search_emits_repeated_schemata_filters() -> None:
    """Multiple ``schemata=[...]`` entries must all reach Aleph as repeated
    ``filter:schemata=<name>`` query params, not collapse to one."""
    seen: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["schemata"] = request.url.params.get_list("filter:schemata")
        return _json({"results": [], "total": 0, "limit": 50})

    with _make_client(handler) as client:
        client.search("", schemata=["Document", "Page"])

    assert seen["schemata"] == ["Document", "Page"]


# ---------------------------------------------------------------------------
# get_entity
# ---------------------------------------------------------------------------


def test_get_entity_round_trip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/2/entities/doc-42"
        return _json(
            {
                "id": "doc-42",
                "schema": "Document",
                "collection_id": "coll-1",
                "properties": {
                    "fileName": ["bank-statement.pdf"],
                    "mimeType": ["application/pdf"],
                },
                "writeable": False,
            }
        )

    with _make_client(handler) as client:
        ent = client.get_entity("doc-42")

    assert ent.id == "doc-42"
    assert ent.schema_ == "Document"
    assert ent.properties["fileName"] == ["bank-statement.pdf"]


def test_get_entity_rejects_blank_id() -> None:
    client = _make_client(lambda r: _json({}))
    with pytest.raises(ValueError):
        client.get_entity("")


def test_get_entity_url_quotes_path_segment() -> None:
    """An LLM-chosen entity_id must not be able to rewrite the request path.

    ``../collections/1`` would otherwise traverse out of /entities/ into a
    different resource — an SSRF / authorization-bypass primitive. We assert
    against ``raw_path`` (the bytes that go on the wire), not ``path``,
    because httpx decodes %-escapes when surfacing ``url.path``.
    """
    seen: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["raw_path"] = request.url.raw_path
        return _json({"id": "x", "schema": "Document", "properties": {}})

    with _make_client(handler) as client:
        client.get_entity("../collections/1")

    assert seen["raw_path"] == b"/api/2/entities/..%2Fcollections%2F1"


# ---------------------------------------------------------------------------
# list_collections
# ---------------------------------------------------------------------------


def test_list_collections_round_trip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/2/collections"
        return _json(
            {
                "results": [
                    {
                        "id": "1",
                        "label": "OLAF Test Corpus",
                        "foreign_id": "olaf-test",
                        "category": "investigation",
                        "countries": ["be"],
                        "languages": ["fr", "nl"],
                    }
                ],
                "total": 1,
                "limit": 50,
            }
        )

    with _make_client(handler) as client:
        cols = client.list_collections()

    assert len(cols) == 1
    col = cols[0]
    assert isinstance(col, Collection)
    assert col.label == "OLAF Test Corpus"
    assert col.languages == ["fr", "nl"]


def test_list_collections_rejects_malformed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"total": 0})  # missing 'results'

    with _make_client(handler) as client:
        with pytest.raises(AlephResponseError):
            client.list_collections()


# ---------------------------------------------------------------------------
# get_document_text — full document
# ---------------------------------------------------------------------------


def test_get_document_text_full_doc_hashes_nfc() -> None:
    # NFD form of 'café'; client must NFC-normalize before hashing.
    nfd = unicodedata.normalize("NFD", "café bancaire")
    expected_text = unicodedata.normalize("NFC", nfd)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/2/entities/doc-1"
        return _json(
            {
                "id": "doc-1",
                "schema": "Document",
                "properties": {"bodyText": [nfd]},
            }
        )

    with _make_client(handler) as client:
        out = client.get_document_text("doc-1")

    assert isinstance(out, DocumentText)
    assert out.doc_id == "doc-1"
    assert out.page is None
    assert out.text == expected_text
    assert out.normalized_text_sha256 == _sha256_nfc(nfd)
    assert out.extractor_version == "tesseract-5.3.1@aleph-3.18"


def test_get_document_text_joins_multivalued_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "id": "doc-1",
                "schema": "Document",
                "properties": {"bodyText": ["chunk one", "chunk two"]},
            }
        )

    with _make_client(handler) as client:
        out = client.get_document_text("doc-1")

    assert out.text == "chunk one\nchunk two"
    assert out.normalized_text_sha256 == _sha256_nfc("chunk one\nchunk two")


def test_get_document_text_missing_body_raises_not_found() -> None:
    # Aleph excludes `bodyText` by default in the detail view; "no bodyText
    # at all" must surface as NotFoundError per the DocumentSource Protocol
    # contract — silent loss (returning empty text) would let the verifier
    # drop real notes for what's actually a config / extraction-not-run bug.
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"id": "doc-1", "schema": "Document", "properties": {}})

    with _make_client(handler) as client:
        with pytest.raises(NotFoundError):
            client.get_document_text("doc-1")


def test_get_document_text_empty_extraction_returns_empty_text() -> None:
    # Distinct from the above: bodyText IS present but the extractor produced
    # no text (legitimate for a blank page / image-only doc with no OCR hits).
    # That's allowed through — the verifier will fail downstream substring
    # checks loudly, which is the correct signal.
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "id": "doc-1",
                "schema": "Document",
                "properties": {"bodyText": [""]},
            }
        )

    with _make_client(handler) as client:
        out = client.get_document_text("doc-1")

    assert out.text == ""
    assert out.normalized_text_sha256 == _sha256_nfc("")


# ---------------------------------------------------------------------------
# get_document_text — single page
# ---------------------------------------------------------------------------


def test_get_document_text_page_filters_by_index() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return _json(
            {
                "results": [
                    {
                        "id": "page-1-3",
                        "schema": "Page",
                        "properties": {
                            "bodyText": ["page three text"],
                            "document": ["doc-1"],
                            "index": ["3"],
                        },
                    }
                ],
                "total": 1,
                "limit": 1,
            }
        )

    with _make_client(handler) as client:
        out = client.get_document_text("doc-1", page=3)

    assert captured["params"]["filter:schemata"] == "Page"
    assert captured["params"]["filter:properties.document"] == "doc-1"
    assert captured["params"]["filter:properties.index"] == "3"
    assert out.page == 3
    assert out.text == "page three text"
    assert out.normalized_text_sha256 == _sha256_nfc("page three text")


def test_get_document_text_missing_page_raises_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"results": [], "total": 0, "limit": 1})

    with _make_client(handler) as client:
        with pytest.raises(NotFoundError):
            client.get_document_text("doc-1", page=99)


def test_get_document_text_page_post_filters_mismatched_doc() -> None:
    """Aleph's filter:properties.* is best-effort — defend against a Page
    that surfaces but actually belongs to a different document."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "results": [
                    {
                        "id": "page-X-3",
                        "schema": "Page",
                        "properties": {
                            "bodyText": ["wrong text"],
                            "document": ["doc-OTHER"],
                            "index": ["3"],
                        },
                    }
                ],
                "total": 1,
                "limit": 1,
            }
        )

    with _make_client(handler) as client:
        with pytest.raises(NotFoundError):
            client.get_document_text("doc-1", page=3)


def test_get_document_text_page_post_filters_mismatched_index() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "results": [
                    {
                        "id": "page-1-7",
                        "schema": "Page",
                        "properties": {
                            "bodyText": ["wrong page"],
                            "document": ["doc-1"],
                            "index": ["7"],
                        },
                    }
                ],
                "total": 1,
                "limit": 1,
            }
        )

    with _make_client(handler) as client:
        with pytest.raises(NotFoundError):
            client.get_document_text("doc-1", page=3)


def test_get_document_text_page_missing_body_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "results": [
                    {
                        "id": "page-1-3",
                        "schema": "Page",
                        "properties": {
                            "document": ["doc-1"],
                            "index": ["3"],
                        },
                    }
                ],
                "total": 1,
                "limit": 1,
            }
        )

    with _make_client(handler) as client:
        with pytest.raises(NotFoundError):
            client.get_document_text("doc-1", page=3)


def test_get_document_text_rejects_invalid_page() -> None:
    client = _make_client(lambda r: _json({}))
    with pytest.raises(ValueError):
        client.get_document_text("doc-1", page=0)
    with pytest.raises(ValueError):
        client.get_document_text("", page=1)


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,exc_type",
    [
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (429, RateLimitError),
        (500, ServerError),
        (503, ServerError),
        (418, AlephHTTPError),  # other 4xx -> base http error
    ],
)
def test_http_status_maps_to_named_exception(status: int, exc_type: type) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"status": "error", "message": f"boom-{status}"}, status=status)

    with _make_client(handler) as client:
        with pytest.raises(exc_type) as exc_info:
            client.get_entity("missing")

    assert exc_info.value.status_code == status
    assert "boom" in exc_info.value.message


def test_non_json_error_body_falls_back_to_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="<html>nginx 500</html>")

    with _make_client(handler) as client:
        with pytest.raises(ServerError) as exc_info:
            client.get_entity("x")

    assert exc_info.value.status_code == 500


def test_invalid_json_response_raises_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json{{")

    with _make_client(handler) as client:
        with pytest.raises(AlephResponseError):
            client.get_entity("x")


def test_non_object_response_raises_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(["not", "an", "object"])

    with _make_client(handler) as client:
        with pytest.raises(AlephResponseError):
            client.get_entity("x")


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda req: httpx.ConnectError("connect failed", request=req),
        lambda req: httpx.ReadTimeout("read timeout", request=req),
        lambda req: httpx.WriteError("write failed", request=req),
        lambda req: httpx.RemoteProtocolError("bad framing", request=req),
    ],
    ids=["connect", "read-timeout", "write", "remote-protocol"],
)
def test_transport_error_wrapped(exc_factory) -> None:
    """Every httpx.RequestError subclass must surface as AlephTransportError.

    These have different semantics for "did Aleph commit the read?" but from
    the audit log's perspective they all mean: we don't know what happened.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise exc_factory(request)

    with _make_client(handler) as client:
        with pytest.raises(AlephTransportError):
            client.search("anything")


# ---------------------------------------------------------------------------
# DocumentSource Protocol — must match src/verifier/substring.py's contract:
# ``get_text(doc_id, page=None) -> str`` + DocumentNotFound / PageNotFound /
# TransientSourceError exceptions. The verifier handles NFC + sha256 itself.
# ---------------------------------------------------------------------------


def test_aleph_document_source_satisfies_protocol() -> None:
    transport = httpx.MockTransport(lambda r: _json({}))
    client = AlephClient(base_url=API_BASE, api_key=API_KEY, transport=transport)
    source = AlephDocumentSource(client)
    assert isinstance(source, DocumentSource)


def test_aleph_document_source_returns_raw_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "id": "doc-1",
                "schema": "Document",
                "properties": {"bodyText": ["hello world"]},
            }
        )

    with _make_client(handler) as client:
        text = AlephDocumentSource(client).get_text("doc-1")

    assert text == "hello world"
    assert isinstance(text, str)


def test_aleph_document_source_full_doc_missing_raises_document_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"status": "error", "message": "no such doc"}, status=404)

    with _make_client(handler) as client:
        with pytest.raises(DocumentNotFound):
            AlephDocumentSource(client).get_text("doc-1")


def test_aleph_document_source_full_doc_missing_body_raises_document_not_found() -> None:
    """An entity with no bodyText is treated as 'doc unverifiable' for the verifier."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"id": "doc-1", "schema": "Document", "properties": {}})

    with _make_client(handler) as client:
        with pytest.raises(DocumentNotFound):
            AlephDocumentSource(client).get_text("doc-1")


def test_aleph_document_source_page_missing_doc_raises_document_not_found() -> None:
    """page=N with a missing doc must surface as DocumentNotFound, not PageNotFound."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"status": "error", "message": "no such doc"}, status=404)

    with _make_client(handler) as client:
        with pytest.raises(DocumentNotFound):
            AlephDocumentSource(client).get_text("doc-1", page=3)


def test_aleph_document_source_page_missing_page_raises_page_not_found() -> None:
    """Doc exists, page does not — the verifier needs PageNotFound, not DocumentNotFound."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/2/entities/doc-1":
            # doc-existence probe succeeds
            return _json(
                {"id": "doc-1", "schema": "Document", "properties": {"fileName": ["x.pdf"]}}
            )
        # page search returns empty
        return _json({"results": [], "total": 0, "limit": 1})

    with _make_client(handler) as client:
        with pytest.raises(PageNotFound):
            AlephDocumentSource(client).get_text("doc-1", page=99)


def test_aleph_document_source_page_returns_text_when_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/2/entities/doc-1":
            return _json(
                {"id": "doc-1", "schema": "Document", "properties": {"fileName": ["x.pdf"]}}
            )
        return _json(
            {
                "results": [
                    {
                        "id": "page-1-3",
                        "schema": "Page",
                        "properties": {
                            "bodyText": ["page three text"],
                            "document": ["doc-1"],
                            "index": ["3"],
                        },
                    }
                ],
                "total": 1,
                "limit": 1,
            }
        )

    with _make_client(handler) as client:
        text = AlephDocumentSource(client).get_text("doc-1", page=3)

    assert text == "page three text"


@pytest.mark.parametrize(
    "make_response",
    [
        lambda req: _json({"status": "error", "message": "rate limited"}, status=429),
        lambda req: _json({"status": "error", "message": "5xx"}, status=500),
        lambda req: _json({"status": "error", "message": "bad gateway"}, status=503),
    ],
    ids=["rate-limit", "server-error", "bad-gateway"],
)
def test_aleph_document_source_retryable_errors_become_transient(make_response) -> None:
    """429 + 5xx must surface as TransientSourceError so the verifier's retry wrapper handles them."""

    def handler(request: httpx.Request) -> httpx.Response:
        return make_response(request)

    with _make_client(handler) as client:
        with pytest.raises(TransientSourceError):
            AlephDocumentSource(client).get_text("doc-1")


def test_aleph_document_source_transport_error_becomes_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down", request=request)

    with _make_client(handler) as client:
        with pytest.raises(TransientSourceError):
            AlephDocumentSource(client).get_text("doc-1")


def test_protocol_accepts_alternative_implementations() -> None:
    """The verifier must be able to substitute a fake source in tests."""

    class FakeSource:
        def get_text(self, doc_id: str, page: int | None = None) -> str:
            return f"fake text for {doc_id} page={page}"

    source = FakeSource()
    assert isinstance(source, DocumentSource)
    assert source.get_text("doc-x", page=2) == "fake text for doc-x page=2"


# ---------------------------------------------------------------------------
# Integration tests — local dev stack only.
# Run with: pytest -m integration
# ---------------------------------------------------------------------------


def _integration_base_url() -> str:
    """Read the per-workspace ALEPH_API_URL from .env.ports.

    Falls back to the env var if set; otherwise skips. Each Conductor
    workspace gets its own port-offset Aleph stack — see bin/dev-init.
    """
    if "ALEPH_API_URL" in os.environ:
        return os.environ["ALEPH_API_URL"]
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.ports"
    )
    if not os.path.exists(env_path):
        pytest.skip(".env.ports not found; run bin/dev-init")
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("ALEPH_API_URL="):
                return line.split("=", 1)[1]
    pytest.skip("ALEPH_API_URL not present in .env.ports")
    return ""  # unreachable; for type-checker


@pytest.mark.integration
def test_integration_list_collections() -> None:
    base_url = _integration_base_url()
    api_key = os.environ.get("ALEPH_API_KEY")
    if not api_key:
        pytest.skip("ALEPH_API_KEY not set; export it to run integration tests")

    with AlephClient(base_url=base_url, api_key=api_key, timeout=10) as client:
        cols = client.list_collections(limit=5)

    assert isinstance(cols, list)
    for col in cols:
        assert isinstance(col, Collection)
        assert col.id
        assert col.label


@pytest.mark.integration
def test_integration_search_smoke() -> None:
    base_url = _integration_base_url()
    api_key = os.environ.get("ALEPH_API_KEY")
    if not api_key:
        pytest.skip("ALEPH_API_KEY not set; export it to run integration tests")

    with AlephClient(base_url=base_url, api_key=api_key, timeout=10) as client:
        out = client.search("test", limit=5)

    assert isinstance(out, SearchResults)
    assert out.limit == 5
