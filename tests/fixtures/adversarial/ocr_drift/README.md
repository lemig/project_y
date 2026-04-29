# Adversarial fixtures — OCR drift pairs

## What this tests

The per-investigation corpus-snapshot tests (workspace D) and, indirectly, the
`planner-drift-on-dep-bump` and `checkpoint-corruption` hard-gated tests in
CLAUDE.md. The point: the same physical scan + same page can produce different
extracted text under different `extractor_version` values, which means the
`normalized_text_sha256` recorded in a `Quote` is **only meaningful** when
paired with the `extractor_version` that produced it.

If the corpus snapshot doesn't capture extractor_version per document, a
re-run with an upgraded OCR pipeline will silently flip the SHA-256 under
existing notes — breaking provenance without breaking any structural test.

## Format

`pairs.json` — schema version `v2-adversarial-ocr-drift-2026-04-29`.

Each entry under `pairs[]`:

| field | meaning |
|---|---|
| `id` | stable handle (test parameter id) |
| `doc_id` | synthetic stand-in for an Aleph doc id |
| `page` | 1-based page number, matches `Quote.page` |
| `what_changed` | one-paragraph description of the OCR-pipeline divergence |
| `extractions` | list of `{extractor_version, normalized_text, normalized_text_utf8_byte_length, normalized_text_sha256, human_readable}` |

For every pair, the `normalized_text_sha256` values across `extractions` are
all distinct — this is the "drift" the fixture is asserting.

## Coverage (6 pairs)

| id | drift pattern |
|---|---|
| `ligature_fi_v4_vs_v5` | Tesseract 4.x emits U+FB01 'ﬁ' ligature; 5.x emits 'fi' two-char sequence |
| `soft_hyphen_drift` | 4.x preserves U+00AD soft hyphens; 5.x strips them |
| `diacritic_loss_old_extractor` | older textract path strips Romanian ț; newer tesseract preserves |
| `zero_o_confusion_old_extractor` | older OCR misread digit 0 as capital O; newer reads correctly |
| `trailing_space_normalization` | aleph-3.16 keeps trailing space at EOL; aleph-3.18 collapses |
| `page_rotation_reordering` | two-column scan: column-major reading vs row-major reading |

These six cover the major drift categories: code-point identity (ligatures,
soft hyphens, diacritics), character-level confusion (0/O), whitespace
normalization, and reading-order changes.

## Invariants asserted at fixture-build time

For every pair: every extraction's `normalized_text_sha256` is distinct from
every other extraction's hash in the same pair. Tests should re-assert this on
load — if a hand-edit ever makes two extractions produce the same hash, the
pair is not actually testing drift any more.

## What the corpus-snapshot system should do

Per CLAUDE.md premise #8 (per-investigation corpus snapshot):

1. The snapshot binds `(doc_id, page) → (extractor_version, normalized_text_sha256)`.
2. Every Note's Quote inherits the binding it was created against.
3. Re-running the investigation MUST replay against the same snapshot.
4. If a re-run uses a doc whose current `extractor_version` differs from the
   snapshot's recorded version, the system MUST treat that as a snapshot miss
   (route to a re-OCR or to a hard fail), not silently produce a different
   `normalized_text_sha256` for the "same" Quote.

The fixtures here let tests prove items 1–4 without spinning up Aleph or
running real OCR. Substitute the recorded extractions in place of an Aleph
fetch and assert the snapshot-binding logic does the right thing.

## Source

Hand-crafted, fully synthetic. Drift patterns are real (every one of the six
is a documented Tesseract / Aleph behavior change), but the specific text
content is invented for these fixtures — no real case material. Hashes were
computed at fixture-build time over the recorded `normalized_text` UTF-8 bytes
using `hashlib.sha256(text.encode("utf-8")).hexdigest()`.
