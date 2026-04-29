"""Tests for the per-investigation corpus snapshot.

Unit tests use ``httpx.MockTransport`` so the suite runs without a live
Aleph stack. The integration test is gated behind ``pytest.mark.integration``
and hits the per-workspace dev stack started by ``bin/dev-up`` — same gating
convention as ``tests/test_aleph_client.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from typing import Any

import httpx
import pytest

from aleph.client import AlephClient, Collection
from aleph.snapshot import (
    CorpusSnapshot,
    ManifestRow,
    snapshot_collection,
)


API_BASE = "http://aleph.test/api/2"
API_KEY = "test-api-key"
EXTRACTOR = "tesseract-5.3.1@aleph-3.18"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(handler) -> AlephClient:
    transport = httpx.MockTransport(handler)
    return AlephClient(
        base_url=API_BASE,
        api_key=API_KEY,
        extractor_version=EXTRACTOR,
        transport=transport,
    )


def _json(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def _doc_entity(doc_id: str, body_text: str | None, schema: str = "PlainText") -> dict:
    """Aleph entity-detail JSON for a Document-descendant. ``body_text=None``
    omits the ``bodyText`` property entirely (Aleph default-view behavior or
    extractor-not-yet-run)."""
    properties: dict[str, list[str]] = {"fileName": [f"{doc_id}.bin"]}
    if body_text is not None:
        properties["bodyText"] = [body_text]
    return {
        "id": doc_id,
        "schema": schema,
        "collection_id": "coll-1",
        "properties": properties,
    }


def _sha256_nfc(s: str) -> str:
    return hashlib.sha256(unicodedata.normalize("NFC", s).encode("utf-8")).hexdigest()


class _Stub:
    """Routable mock for the four endpoints snapshot touches.

    The snapshot first walks ``GET /entities`` (with ``filter:schemata=Document``
    + ``filter:collection_id``), then for each result calls ``GET /entities/{id}``
    via ``get_document_text`` (page=None), and for ``Pages``-schema entities
    issues another ``GET /entities`` to count Page children.
    """

    def __init__(
        self,
        *,
        listings: list[list[dict]],
        entity_details: dict[str, dict],
        page_totals: dict[str, int] | None = None,
    ) -> None:
        # listings[i] is the entities returned at offset = i * page_size.
        self.listings = listings
        self.entity_details = entity_details
        self.page_totals = page_totals or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        params = request.url.params

        if path.startswith("/api/2/entities/"):
            entity_id = path[len("/api/2/entities/") :]
            # path quoting: tests here only use simple ids, no escaping.
            return _json(self.entity_details[entity_id])

        if path == "/api/2/entities":
            # Disambiguate enumeration vs. page-count by the schemata filter.
            schemata = params.get_list("filter:schemata")
            if "Page" in schemata:
                doc_id = params.get("filter:properties.document", "")
                return _json(
                    {
                        "results": [],
                        "total": self.page_totals.get(doc_id, 0),
                        "limit": int(params.get("limit", "1")),
                        "offset": 0,
                    }
                )
            # Document enumeration.
            offset = int(params.get("offset", "0"))
            limit = int(params.get("limit", "200"))
            page_idx = offset // limit if limit else 0
            results = (
                self.listings[page_idx] if page_idx < len(self.listings) else []
            )
            total = sum(len(p) for p in self.listings)
            return _json(
                {"results": results, "total": total, "limit": limit, "offset": offset}
            )

        raise AssertionError(f"unexpected path: {path}")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_snapshot_round_trip_single_page_doc() -> None:
    body = "hello world"
    stub = _Stub(
        listings=[[_doc_entity("doc-1", body, schema="PlainText")]],
        entity_details={"doc-1": _doc_entity("doc-1", body, schema="PlainText")},
    )
    with _make_client(stub) as client:
        snap = snapshot_collection(client, "coll-1")

    assert isinstance(snap, CorpusSnapshot)
    assert snap.collection_id == "coll-1"
    assert snap.row_count == 1
    expected_row = {
        "doc_id": "doc-1",
        "sha256_normalized_text": _sha256_nfc(body),
        "extractor_version": EXTRACTOR,
        "page_count": None,
    }
    assert snap.manifest_jsonl == json.dumps(
        expected_row, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert snap.corpus_snapshot_hash == hashlib.sha256(snap.manifest_jsonl).hexdigest()


def test_snapshot_rejects_blank_collection_id() -> None:
    with _make_client(lambda r: _json({})) as client:
        with pytest.raises(ValueError):
            snapshot_collection(client, "")


def test_snapshot_empty_collection_returns_empty_manifest() -> None:
    stub = _Stub(listings=[[]], entity_details={})
    with _make_client(stub) as client:
        snap = snapshot_collection(client, "coll-1")

    assert snap.row_count == 0
    assert snap.manifest_jsonl == b""
    assert snap.corpus_snapshot_hash == hashlib.sha256(b"").hexdigest()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_snapshot_is_deterministic_across_input_order() -> None:
    """Aleph may reorder results between paginated calls. The manifest hash
    must depend only on the SET of (doc_id, text) pairs, not the order Aleph
    returns them — otherwise the audit log links break on replay."""
    bodies = {"doc-A": "alpha", "doc-B": "beta", "doc-C": "gamma"}

    def stub_for(order: list[str]) -> _Stub:
        listings = [[_doc_entity(d, bodies[d], schema="PlainText") for d in order]]
        details = {d: _doc_entity(d, bodies[d], schema="PlainText") for d in order}
        return _Stub(listings=listings, entity_details=details)

    with _make_client(stub_for(["doc-A", "doc-B", "doc-C"])) as c1:
        snap_a = snapshot_collection(c1, "coll-1")
    with _make_client(stub_for(["doc-C", "doc-A", "doc-B"])) as c2:
        snap_b = snapshot_collection(c2, "coll-1")

    assert snap_a.manifest_jsonl == snap_b.manifest_jsonl
    assert snap_a.corpus_snapshot_hash == snap_b.corpus_snapshot_hash


def test_snapshot_canonical_jsonl_format() -> None:
    """JSONL: lines joined with single \\n, no trailing newline, sorted keys,
    no extra whitespace. These bytes are what gets hashed."""
    bodies = {"doc-1": "alpha", "doc-2": "beta"}
    listings = [[_doc_entity(d, bodies[d]) for d in bodies]]
    details = {d: _doc_entity(d, bodies[d]) for d in bodies}
    stub = _Stub(listings=listings, entity_details=details)

    with _make_client(stub) as client:
        snap = snapshot_collection(client, "coll-1")

    text = snap.manifest_jsonl.decode("utf-8")
    assert not text.endswith("\n")
    lines = text.split("\n")
    assert len(lines) == 2
    # Sorted by doc_id.
    parsed = [json.loads(line) for line in lines]
    assert [r["doc_id"] for r in parsed] == ["doc-1", "doc-2"]
    # Compact separators, sorted keys: a re-serialized round-trip must equal
    # the original line bytes.
    for line, row in zip(lines, parsed):
        assert (
            json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            == line
        )
    # No spaces between separators.
    assert ", " not in text
    assert ": " not in text


# ---------------------------------------------------------------------------
# Multi-page docs
# ---------------------------------------------------------------------------


def test_snapshot_records_page_count_for_pages_schema() -> None:
    body = "page1\npage2\npage3"
    stub = _Stub(
        listings=[[_doc_entity("doc-1", body, schema="Pages")]],
        entity_details={"doc-1": _doc_entity("doc-1", body, schema="Pages")},
        page_totals={"doc-1": 3},
    )
    with _make_client(stub) as client:
        snap = snapshot_collection(client, "coll-1")

    row = json.loads(snap.manifest_jsonl)
    assert row["page_count"] == 3


def test_snapshot_does_not_query_pages_for_non_paginated_schemas() -> None:
    """A PlainText/Image entity has no Page children — issuing a count query
    for it would be wasted I/O. Multiplied by 100s of docs it adds up."""
    stub = _Stub(
        listings=[[_doc_entity("doc-1", "hello", schema="PlainText")]],
        entity_details={"doc-1": _doc_entity("doc-1", "hello", schema="PlainText")},
    )
    with _make_client(stub) as client:
        snapshot_collection(client, "coll-1")

    page_lookups = [
        r
        for r in stub.requests
        if r.url.path == "/api/2/entities"
        and "Page" in r.url.params.get_list("filter:schemata")
    ]
    assert page_lookups == []


# ---------------------------------------------------------------------------
# Skipping behavior
# ---------------------------------------------------------------------------


def test_snapshot_skips_folders_quietly(caplog) -> None:
    """Folder entities are structural — they carry no bodyText by design and
    their absence from the manifest is expected. Logged at INFO, never
    counted as a suspicious skip."""
    listings = [
        [
            _doc_entity("doc-folder", None, schema="Folder"),
            _doc_entity("doc-1", "actual content", schema="PlainText"),
        ]
    ]
    details = {
        "doc-folder": _doc_entity("doc-folder", None, schema="Folder"),
        "doc-1": _doc_entity("doc-1", "actual content", schema="PlainText"),
    }
    stub = _Stub(listings=listings, entity_details=details)

    with _make_client(stub) as client:
        with caplog.at_level("INFO", logger="aleph.snapshot"):
            snap = snapshot_collection(client, "coll-1")

    assert snap.row_count == 1
    rows = [json.loads(line) for line in snap.manifest_jsonl.decode().split("\n")]
    assert [r["doc_id"] for r in rows] == ["doc-1"]
    folder_skips = [r for r in caplog.records if "snapshot.skip_folder" in r.message]
    suspicious = [r for r in caplog.records if "snapshot.skip_no_body_text" in r.message]
    partial = [r for r in caplog.records if "snapshot.partial" in r.message]
    assert len(folder_skips) == 1
    assert folder_skips[0].levelname == "INFO"
    assert suspicious == []
    assert partial == []


def test_snapshot_warns_when_extraction_incomplete(caplog) -> None:
    """A non-Folder Document-descendant with no bodyText is almost always a
    half-extracted corpus or a deployment that excludes ``bodyText`` from
    the API. Silent skip would shrink the manifest invisibly, so we WARN +
    increment a counter that surfaces as a 'snapshot.partial' WARNING at
    the end of the run. CLAUDE.md's no-silent-loss principle in spirit."""
    listings = [
        [
            _doc_entity("doc-broken", None, schema="PlainText"),
            _doc_entity("doc-ok", "actual content", schema="PlainText"),
        ]
    ]
    details = {
        "doc-broken": _doc_entity("doc-broken", None, schema="PlainText"),
        "doc-ok": _doc_entity("doc-ok", "actual content", schema="PlainText"),
    }
    stub = _Stub(listings=listings, entity_details=details)

    with _make_client(stub) as client:
        with caplog.at_level("WARNING", logger="aleph.snapshot"):
            snap = snapshot_collection(client, "coll-1")

    assert snap.row_count == 1
    skip_warnings = [
        r for r in caplog.records if "snapshot.skip_no_body_text" in r.message
    ]
    partial_warnings = [
        r for r in caplog.records if "snapshot.partial" in r.message
    ]
    assert len(skip_warnings) == 1
    assert skip_warnings[0].levelname == "WARNING"
    assert len(partial_warnings) == 1
    assert partial_warnings[0].levelname == "WARNING"


def test_snapshot_warns_on_pages_schema_with_zero_children(caplog) -> None:
    """A Pages-schema doc with no Page children is almost always pipeline
    incompleteness, not a legitimate 'this doc has no pages'. Falling back
    to None is OK (the manifest stays serializable), but the warning lets
    the operator notice."""
    stub = _Stub(
        listings=[[_doc_entity("doc-1", "body", schema="Pages")]],
        entity_details={"doc-1": _doc_entity("doc-1", "body", schema="Pages")},
        page_totals={"doc-1": 0},
    )

    with _make_client(stub) as client:
        with caplog.at_level("WARNING", logger="aleph.snapshot"):
            snap = snapshot_collection(client, "coll-1")

    row = json.loads(snap.manifest_jsonl)
    assert row["page_count"] is None
    zero_warnings = [
        r for r in caplog.records if "snapshot.pages_schema_zero_children" in r.message
    ]
    assert len(zero_warnings) == 1


def test_snapshot_page_count_query_is_scoped_by_collection(caplog) -> None:
    """``filter:properties.*`` is best-effort per Aleph's docs. Without
    ``filter:collection_id`` on the page-count query, a Page in another
    collection that referenced the same parent id could inflate
    ``page_count`` (sha256-derived FtM ids make collisions vanishingly rare,
    but cheap defense > silent corruption). Verify the request includes
    the scope."""
    stub = _Stub(
        listings=[[_doc_entity("doc-1", "body", schema="Pages")]],
        entity_details={"doc-1": _doc_entity("doc-1", "body", schema="Pages")},
        page_totals={"doc-1": 5},
    )
    with _make_client(stub) as client:
        snapshot_collection(client, "coll-XYZ")

    page_lookups = [
        r
        for r in stub.requests
        if r.url.path == "/api/2/entities"
        and "Page" in r.url.params.get_list("filter:schemata")
    ]
    assert len(page_lookups) == 1
    assert page_lookups[0].url.params["filter:collection_id"] == "coll-XYZ"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_snapshot_requests_stable_sort_during_enumeration() -> None:
    """The Document enumeration must include ``sort=caption:asc`` so that
    paginated reads against a mutating corpus stay reasonably stable.
    Without it, Aleph's EntitiesQuery defaults to no sort, falling back to
    unstable ES ``_doc`` ordering — pages can skip docs entirely under
    concurrent writes."""
    body = "alpha"
    stub = _Stub(
        listings=[[_doc_entity("doc-1", body)]],
        entity_details={"doc-1": _doc_entity("doc-1", body)},
    )
    with _make_client(stub) as client:
        snapshot_collection(client, "coll-1")

    enumeration_calls = [
        r
        for r in stub.requests
        if r.url.path == "/api/2/entities"
        and "Document" in r.url.params.get_list("filter:schemata")
    ]
    assert len(enumeration_calls) >= 1
    for call in enumeration_calls:
        assert call.url.params.get("sort") == "caption:asc"


def test_snapshot_detects_duplicate_yields_loudly(caplog) -> None:
    """If pagination races with corpus mutation and Aleph yields the same
    doc_id on two different pages, the dict-dedup absorbs the duplicate
    silently. That same race likely DROPPED a different doc from the
    listing — the manifest would be invisibly incomplete. Detection +
    logging upgrades silent corruption to operator-visible warning."""

    class DuplicatingStub(_Stub):
        def __init__(self) -> None:
            doc = _doc_entity("doc-1", "alpha")
            super().__init__(
                listings=[[doc], [doc]],
                entity_details={"doc-1": doc},
            )
            self.calls = 0

        def __call__(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            path = request.url.path
            params = request.url.params
            if path.startswith("/api/2/entities/"):
                return _json(self.entity_details["doc-1"])
            if path == "/api/2/entities":
                schemata = params.get_list("filter:schemata")
                if "Page" in schemata:
                    return _json(
                        {"results": [], "total": 0, "limit": 1, "offset": 0}
                    )
                # First listing call: serve the doc with total=2 so the
                # outer loop pages again. Second call: serve the SAME doc
                # again (the simulated reorder).
                self.calls += 1
                if self.calls == 1:
                    return _json(
                        {
                            "results": [self.entity_details["doc-1"]],
                            "total": 2,
                            "limit": 200,
                            "offset": 0,
                        }
                    )
                if self.calls == 2:
                    return _json(
                        {
                            "results": [self.entity_details["doc-1"]],
                            "total": 2,
                            "limit": 200,
                            "offset": 1,
                        }
                    )
                return _json(
                    {"results": [], "total": 2, "limit": 200, "offset": 2}
                )
            raise AssertionError(path)

    stub = DuplicatingStub()
    with _make_client(stub) as client:
        with caplog.at_level("WARNING", logger="aleph.snapshot"):
            snap = snapshot_collection(client, "coll-1")

    # One unique doc kept, but the duplicate-yield warning fires.
    assert snap.row_count == 1
    duplicate_warnings = [
        r for r in caplog.records if "snapshot.duplicate_yield" in r.message
    ]
    partial_warnings = [
        r for r in caplog.records if "snapshot.partial" in r.message
    ]
    assert len(duplicate_warnings) == 1
    assert duplicate_warnings[0].levelname == "WARNING"
    assert len(partial_warnings) == 1


def test_snapshot_walks_all_listing_pages() -> None:
    """Snapshot must page through `GET /entities` until the listing is
    exhausted. We size two pages with one doc each, served via offset/limit."""
    bodies = {f"doc-{i}": f"text-{i}" for i in range(5)}
    # Split into two pages: 3 + 2.
    page_a = [_doc_entity(f"doc-{i}", bodies[f"doc-{i}"]) for i in range(3)]
    page_b = [_doc_entity(f"doc-{i}", bodies[f"doc-{i}"]) for i in range(3, 5)]

    class PaginatingStub(_Stub):
        def __init__(self) -> None:
            super().__init__(
                listings=[page_a, page_b],
                entity_details={d: _doc_entity(d, bodies[d]) for d in bodies},
            )
            self.page_size = 3

        def __call__(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            path = request.url.path
            params = request.url.params
            if path.startswith("/api/2/entities/"):
                entity_id = path[len("/api/2/entities/") :]
                return _json(self.entity_details[entity_id])
            if path == "/api/2/entities":
                schemata = params.get_list("filter:schemata")
                if "Page" in schemata:
                    return _json(
                        {"results": [], "total": 0, "limit": 1, "offset": 0}
                    )
                offset = int(params.get("offset", "0"))
                if offset == 0:
                    return _json(
                        {
                            "results": page_a,
                            "total": 5,
                            "limit": self.page_size,
                            "offset": 0,
                        }
                    )
                if offset == self.page_size:
                    return _json(
                        {
                            "results": page_b,
                            "total": 5,
                            "limit": self.page_size,
                            "offset": offset,
                        }
                    )
                return _json(
                    {"results": [], "total": 5, "limit": self.page_size, "offset": offset}
                )
            raise AssertionError(path)

    stub = PaginatingStub()
    with _make_client(stub) as client:
        snap = snapshot_collection(client, "coll-1")

    assert snap.row_count == 5
    # Two listing calls (offset=0, offset=page_size). Don't over-spec the third
    # offset because the generator stops once `offset >= total`.
    listing_calls = [
        r
        for r in stub.requests
        if r.url.path == "/api/2/entities"
        and "Document" in r.url.params.get_list("filter:schemata")
    ]
    assert len(listing_calls) == 2


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


def test_snapshot_re_snapshot_produces_same_hash() -> None:
    """Two snapshots of an unchanged corpus must hash to the same value —
    that's the whole point of the manifest.+hash design."""
    bodies = {"doc-A": "alpha", "doc-B": "beta"}
    listings = [[_doc_entity(d, bodies[d]) for d in bodies]]
    details = {d: _doc_entity(d, bodies[d]) for d in bodies}

    h1 = ""
    h2 = ""
    for sink in (1, 2):
        stub = _Stub(listings=listings, entity_details=details)
        with _make_client(stub) as client:
            snap = snapshot_collection(client, "coll-1")
        if sink == 1:
            h1 = snap.corpus_snapshot_hash
        else:
            h2 = snap.corpus_snapshot_hash

    assert h1 == h2 != ""


def test_snapshot_text_change_produces_different_hash() -> None:
    """Flip side: any text drift in any document MUST change the snapshot
    hash. Otherwise replay can't notice a corpus mutation."""
    listings_v1 = [[_doc_entity("doc-1", "v1 text", schema="PlainText")]]
    details_v1 = {"doc-1": _doc_entity("doc-1", "v1 text", schema="PlainText")}
    stub_v1 = _Stub(listings=listings_v1, entity_details=details_v1)

    listings_v2 = [[_doc_entity("doc-1", "v2 text", schema="PlainText")]]
    details_v2 = {"doc-1": _doc_entity("doc-1", "v2 text", schema="PlainText")}
    stub_v2 = _Stub(listings=listings_v2, entity_details=details_v2)

    with _make_client(stub_v1) as c1:
        snap_v1 = snapshot_collection(c1, "coll-1")
    with _make_client(stub_v2) as c2:
        snap_v2 = snapshot_collection(c2, "coll-1")

    assert snap_v1.corpus_snapshot_hash != snap_v2.corpus_snapshot_hash


# ---------------------------------------------------------------------------
# Manifest row shape
# ---------------------------------------------------------------------------


def test_manifest_row_is_frozen() -> None:
    """ManifestRow must be hashable + immutable so callers can't tamper with
    a snapshot post-hoc and present a different manifest."""
    row = ManifestRow(
        doc_id="doc-1",
        sha256_normalized_text="x" * 64,
        extractor_version=EXTRACTOR,
        page_count=None,
    )
    with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError
        row.doc_id = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Integration — local dev stack only
# ---------------------------------------------------------------------------


def _integration_base_url() -> str:
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
def test_integration_snapshot_first_collection_is_deterministic() -> None:
    """Snapshot the first visible collection twice; the corpus must be
    static between the two calls (we run on a dev stack with no concurrent
    ingest), so both snapshot hashes must agree."""
    base_url = _integration_base_url()
    api_key = os.environ.get("ALEPH_API_KEY")
    if not api_key:
        pytest.skip("ALEPH_API_KEY not set; export it to run integration tests")

    with AlephClient(
        base_url=base_url,
        api_key=api_key,
        timeout=30,
        extractor_version=EXTRACTOR,
    ) as client:
        cols: list[Collection] = client.list_collections(limit=5)
        if not cols:
            pytest.skip("dev Aleph stack has no collections; ingest a corpus first")

        target = cols[0]
        snap_a = snapshot_collection(client, target.id)
        snap_b = snapshot_collection(client, target.id)

    assert snap_a.collection_id == target.id
    # An empty collection still produces a valid (empty) manifest, but the
    # hash must agree on a re-snapshot regardless of row count.
    assert snap_a.corpus_snapshot_hash == snap_b.corpus_snapshot_hash
    assert snap_a.manifest_jsonl == snap_b.manifest_jsonl
