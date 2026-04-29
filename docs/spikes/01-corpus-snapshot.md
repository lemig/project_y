# Spike 1 — Per-investigation corpus snapshot

**Date:** 2026-04-29
**Reviewer:** Miguel Cabero (lemig)
**Verdict:** **USE FALLBACK** — manifest + sha256. OpenAleph has no native
snapshot mechanism.

## Question

Architectural premise #8 (`CLAUDE.md`) requires every Note to carry
`source_corpus_snapshot_hash` (`src/schema/note.py:124`) so the audit trail can
replay against the exact corpus state at investigation time. The premise:
"native Aleph snapshot if Spike 1 succeeds, else manifest+hash fallback".
Does OpenAleph (3.18 line, our pinned substrate) expose such a mechanism?

## Method

Read-only review of `~/conductor/repos/openaleph` (the OpenAleph reference
repo). Searched for:

- snapshot endpoints (`aleph/views/`)
- per-document version pinning, revisions, "as-of" queries
- Elasticsearch snapshot API integration
- collection-level versioning, freeze, or read-only pinning
- export/archive APIs that could substitute as a snapshot source

Did not bring up `bin/dev-up`. The structural absence found in source review is
not configuration-dependent — an endpoint that does not exist in source code
cannot exist at runtime.

## Findings

### No native snapshot

- The only matches for `snapshot` (case-insensitive) in the repo are Jest UI
  test snapshots under `ui/src/react-ftm/`. No data-snapshot endpoints, no
  collection freeze, no "as-of" query parameters.
- `aleph/views/entities_api.py` (the relevant REST surface) exposes
  `GET /api/2/entities`, `GET /api/2/entities/{id}`, `GET /api/2/documents/{id}`
  and friends. None take a snapshot or temporal parameter.
- No Elasticsearch snapshot API calls anywhere in the source.

### Per-document state is mutable

- `Document` exposes `content_hash` (sha256 of the binary file) plus
  `created_at` / `updated_at` (`aleph/model/document.py`). The hash is exposed
  via REST as `contentHash` only in **detail-view** entity responses
  (`aleph/views/serializers.py:243-251`).
- Re-ingesting a document with the same `foreign_id` updates the row in place;
  there is no revision history. `updated_at` moves; the document id stays.
- Manually-edited entities (non-document FtM entities, edited via
  `POST /api/2/entities/{id}`) carry no content hash at all. State is JSONB in
  Postgres with no trail.

### Collection state: only `data_updated_at`

- Migration `aleph/migrate/versions/274270e01613_data_updated_at.py` adds a
  single `data_updated_at` timestamp on the collection that bumps when its
  data changes. Useful as a sanity check, not a snapshot mechanism — it cannot
  reconstruct state from a past instant.

## Verdict — USE FALLBACK

Native snapshot does not exist. We commit to the manifest + sha256 fallback.

## Fallback design

### Manifest format

JSONL, UTF-8. One row per document in the collection. Rows sorted by `doc_id`
so the same corpus produces the same manifest bytes deterministically.

| Field                      | Type        | Notes |
|----------------------------|-------------|-------|
| `doc_id`                   | string      | Aleph entity id of the document. |
| `sha256_normalized_text`   | hex string  | sha256 of the document's normalized extracted text. Matches `Quote.normalized_text_sha256` in `src/schema/note.py:59`. |
| `extractor_version`        | string      | e.g. `"tesseract-5.3.1@aleph-3.18"`. Matches `Quote.extractor_version`. |
| `page_count`               | int \| null | `null` for non-paginated docs. |

We deliberately do **not** store Aleph's binary `content_hash`. The agent
reasons over extracted text, not bytes; pinning the binary does not pin the
OCR/extractor combination that produced the text. Quote provenance hashes
the normalized text (`src/schema/note.py:63-66`); the manifest must agree.

### Snapshot operation

1. Page through `GET /api/2/entities?filter:collection_id={id}` to enumerate
   all documents in the collection.
2. For each document, fetch normalized text + extractor metadata via the Aleph
   REST client (workspace B). Compute `sha256_normalized_text`.
3. Build a `ManifestRow` per document.
4. Sort rows by `doc_id`. Serialize each as canonical JSON (sorted keys,
   compact separators), one per line, no trailing newline.
5. `corpus_snapshot_hash = sha256(manifest_jsonl_bytes)` — the value that
   lands on every Note's `source_corpus_snapshot_hash`.

### Caveats

- Aleph collections are mutable by design. Capturing the manifest does not
  prevent the underlying collection from changing afterwards. Replay must
  re-fetch each document and verify against the manifest, or run against an
  archived bulk export.
- The manifest is document-only. v2 does not snapshot manually-edited entities
  (none of v2's starter skills depend on edited entities); revisit in v3 if
  the cross-reference-pep skill graduates from placeholder.
- For the conference demo (Limassol, June 2026) the corpus is set up once and
  not mutated, so the caveat above is academic. For OLAF prod we will revisit
  whether to also archive the binary blobs at snapshot time.

## Stub

`src/aleph/snapshot.py` exposes the interface (`ManifestRow`, `CorpusSnapshot`,
`snapshot_collection`) with implementation deferred — workspaces C and E–K can
import these names today; the body lands once workspace B's Aleph REST client
is merged.

**Status: implemented.** `snapshot_collection` now drives the real Aleph REST
client per the design above. Tests in `tests/test_snapshot.py` cover canonical
JSONL format, deterministic ordering across input permutations, multi-page
counting, no-bodyText skipping with audit-log entry, pagination, and
re-snapshot idempotence; an integration test (`-m integration`) snapshots the
first visible collection on the per-workspace dev stack twice and asserts the
hash matches.
