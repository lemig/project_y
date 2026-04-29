"""Per-investigation corpus snapshot — manifest+hash fallback.

OpenAleph has no native snapshot mechanism (Spike 1 verdict; see
`docs/spikes/01-corpus-snapshot.md`). We freeze a collection's state at
investigation time by walking all documents via Aleph REST, emitting one
JSONL row per document, then sha256-ing the canonical manifest bytes. The
resulting hash is the value carried by every Note's
`source_corpus_snapshot_hash` (`src/schema/note.py:124`).

This module is a STUB. The interface — `ManifestRow`, `CorpusSnapshot`,
`snapshot_collection` — is committed so downstream workspaces (C and E–K)
can import these names. Implementation lands once workspace B's Aleph REST
client is merged.
"""

from __future__ import annotations

from dataclasses import dataclass


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


def snapshot_collection(client: object, collection_id: str) -> CorpusSnapshot:
    """Compute the manifest+hash snapshot for an Aleph collection.

    `client` is workspace B's Aleph REST client (not yet merged at the time
    this stub lands). Implementation deferred — see
    `docs/spikes/01-corpus-snapshot.md` for the design.
    """
    raise NotImplementedError(
        "Stub. See docs/spikes/01-corpus-snapshot.md for the manifest+hash design."
    )
