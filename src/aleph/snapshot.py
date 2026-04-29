"""Per-investigation corpus snapshot — manifest+hash fallback.

OpenAleph has no native snapshot mechanism (Spike 1 verdict; see
`docs/spikes/01-corpus-snapshot.md`). We freeze a collection's state at
investigation time by walking all documents via Aleph REST, emitting one
JSONL row per document, then sha256-ing the canonical manifest bytes. The
resulting hash is the value carried by every Note's
`source_corpus_snapshot_hash` (`src/schema/note.py:124`).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass

from aleph.client import AlephClient, Entity, NotFoundError

log = logging.getLogger(__name__)

# Page size for the Aleph entities listing during enumeration. Aleph caps
# `limit` at 10_000 per call but we keep this conservative so a slow extractor
# response doesn't time out a whole page batch.
_ENUM_PAGE_SIZE = 200

# In FtM today, ``Pages`` is the only schema representing a multi-page file
# (PDFs, slideshows, multi-sheet workbooks are stored as ``Pages``). Page
# children point at their parent via ``properties.document`` with a 1-based
# ``properties.index``. If FtM ever adds descendants of ``Pages``, extend this
# set — or move to a runtime ``schema.is_a("Pages")`` lookup if/when the
# followthemoney lib gets adopted as a dep (CLAUDE.md license review pending).
_MULTI_PAGE_SCHEMAS = frozenset({"Pages"})


@dataclass(frozen=True)
class ManifestRow:
    """One row of the corpus snapshot manifest, per document."""

    doc_id: str
    sha256_normalized_text: str
    extractor_version: str
    page_count: int | None


@dataclass(frozen=True)
class CorpusSnapshot:
    """Result of snapshotting a collection.

    `corpus_snapshot_hash` is the sha256 of `manifest_jsonl` and is the value
    that goes into Note.source_corpus_snapshot_hash.
    """

    collection_id: str
    manifest_jsonl: bytes
    corpus_snapshot_hash: str
    row_count: int


def snapshot_collection(client: AlephClient, collection_id: str) -> CorpusSnapshot:
    """Compute the manifest+hash snapshot for an Aleph collection.

    Walks every Document-descendant entity in the collection, fetches its
    extracted text, and emits one canonical JSONL row per document. The rows
    are sorted by ``doc_id`` so the same corpus produces the same manifest
    bytes deterministically; the snapshot hash is sha256 over those bytes.

    Entities that don't carry ``bodyText`` (e.g. Folders, or Documents whose
    extractor pipeline hasn't completed) are skipped from the manifest. Each
    skip is logged with the doc_id so the operator can spot a partial
    extraction before publishing the corpus to investigators.

    Transient Aleph failures (transport, 5xx, 429) propagate — the snapshot
    is an atomic operation. The caller should retry the whole snapshot on
    those errors rather than carrying a partial manifest forward.
    """
    if not collection_id:
        raise ValueError("collection_id must be a non-empty string")

    rows_by_id: dict[str, ManifestRow] = {}
    suspicious_skips = 0
    duplicate_yields = 0

    for entity in _iter_documents(client, collection_id):
        if entity.id in rows_by_id:
            # Same doc_id served twice across paginated calls. Aleph's
            # default ordering is unstable across pages on a mutating
            # corpus; ``_iter_documents`` requests ``sort=caption:asc`` to
            # mitigate, but ties + concurrent writes can still drift.
            # Log it loudly — silent dedup would let the manifest skip
            # docs that drifted past the offset window during the
            # reorder.
            duplicate_yields += 1
            log.warning(
                "snapshot.duplicate_yield",
                extra={"doc_id": entity.id, "collection_id": collection_id},
            )
            continue
        try:
            doc_text = client.get_document_text(entity.id)
        except NotFoundError:
            # No bodyText on this entity. For Folder it's structural and
            # expected (folders carry no text). For any other Document-
            # descendant it's suspicious — extractor pipeline failed, the
            # deployment is excluding bodyText from the API response, or the
            # entity disappeared mid-snapshot (delete-race). All three cases
            # would silently shrink the manifest and skew the corpus hash, so
            # non-Folder skips log at WARNING and increment a counter that
            # surfaces at the end of the run.
            if entity.schema_ == "Folder":
                log.info(
                    "snapshot.skip_folder",
                    extra={"doc_id": entity.id, "schema": entity.schema_},
                )
            else:
                suspicious_skips += 1
                log.warning(
                    "snapshot.skip_no_body_text",
                    extra={"doc_id": entity.id, "schema": entity.schema_},
                )
            continue

        page_count = _page_count(client, entity, collection_id)
        rows_by_id[entity.id] = ManifestRow(
            doc_id=entity.id,
            sha256_normalized_text=doc_text.normalized_text_sha256,
            extractor_version=doc_text.extractor_version,
            page_count=page_count,
        )

    if suspicious_skips or duplicate_yields:
        log.warning(
            "snapshot.partial",
            extra={
                "collection_id": collection_id,
                "suspicious_skips": suspicious_skips,
                "duplicate_yields": duplicate_yields,
                "kept_rows": len(rows_by_id),
            },
        )

    rows = sorted(rows_by_id.values(), key=lambda r: r.doc_id)
    manifest_jsonl = _serialize_manifest(rows)
    return CorpusSnapshot(
        collection_id=collection_id,
        manifest_jsonl=manifest_jsonl,
        corpus_snapshot_hash=hashlib.sha256(manifest_jsonl).hexdigest(),
        row_count=len(rows),
    )


def _iter_documents(client: AlephClient, collection_id: str):
    """Yield every Document-descendant entity in the collection.

    Pagination uses ``offset+limit`` rather than the response ``next`` URL —
    Aleph's REST API is stable on this contract and we already validate
    response shape via the search() pydantic model. Aleph expands
    ``filter:schemata=Document`` to descendants (Pages, Image, PlainText, …),
    so a single filter covers every file-shaped entity.

    ``sort=caption:asc`` is the strongest stable sort the Aleph + ES stack
    permits without server-side config changes: ``_id`` isn't sortable in
    modern ES without ``index.indices.id_field_data.enabled``, and the
    EntitiesQuery defaults to ``SORT_DEFAULT=[]`` which produces unstable
    ``_doc`` ordering across pages on a mutating corpus. ``caption`` is a
    keyword-mapped FtM-derived field present on every Document descendant.
    For investigative corpora ``caption`` resolves to ``fileName`` which is
    effectively unique; ties fall back to ES default tiebreak (still
    unstable on mutation, but the duplicate-yield detector in
    ``snapshot_collection`` makes drift loud rather than silent.)
    """
    offset = 0
    while True:
        page = client.search(
            query="",
            collection_id=collection_id,
            schemata=["Document"],
            sort="caption:asc",
            limit=_ENUM_PAGE_SIZE,
            offset=offset,
        )
        if not page.results:
            return
        for entity in page.results:
            yield entity
        offset += len(page.results)
        # Defensive belt-and-braces: Aleph reports `total` per page; once
        # we've matched it, stop. Avoids an extra empty round-trip when the
        # collection size is exactly a multiple of _ENUM_PAGE_SIZE.
        if offset >= page.total:
            return


def _page_count(
    client: AlephClient, entity: Entity, collection_id: str
) -> int | None:
    """Return the number of Page children for a multi-page document.

    Scoped by ``collection_id`` so a Page in a different collection that
    happened to reference the same parent doc id (FtM ids are sha256-derived
    and collisions are vanishingly unlikely, but ``filter:properties.*`` is
    documented as best-effort by Aleph — see ``client.py``) cannot bleed in.

    Returns ``None`` for single-page / non-paginated docs so the manifest
    JSON serializes that field as ``null`` (the spec at
    ``docs/spikes/01-corpus-snapshot.md`` requires that exact distinction).
    A ``Pages``-schema doc with zero matched Page children logs a warning
    before falling back to ``None``: that combination almost always means
    the page-extraction pipeline didn't finish, not "this doc has no pages".
    """
    if entity.schema_ not in _MULTI_PAGE_SCHEMAS:
        return None
    pages = client.search(
        query="",
        collection_id=collection_id,
        schemata=["Page"],
        filters={"properties.document": entity.id},
        limit=1,
    )
    if pages.total > 0:
        return pages.total
    log.warning(
        "snapshot.pages_schema_zero_children",
        extra={"doc_id": entity.id, "collection_id": collection_id},
    )
    return None


def _serialize_manifest(rows: list[ManifestRow]) -> bytes:
    """Render rows as canonical JSONL — sorted keys, compact, no trailing NL.

    Determinism matters: the bytes of this manifest are hashed to produce
    ``corpus_snapshot_hash``. Any drift in serialization (key order,
    separators, trailing newline) would silently invalidate every Note's
    ``source_corpus_snapshot_hash`` linkage on the next snapshot.
    """
    lines = [
        json.dumps(asdict(r), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for r in rows
    ]
    return "\n".join(lines).encode("utf-8")
