# Adversarial fixtures — Unicode NFC/NFD pairs

## What this tests

`brief-hash canonicality` and `audit-log dedup` (two of the six hard-gated bug-class
tests in CLAUDE.md) must treat NFC-composed and NFD-decomposed forms of the same
string as identical inputs. If they don't, two analysts working on the same case
in different OS / OCR pipelines will produce notes that look semantically equal but
hash differently — silently splitting the audit trail.

These fixtures are also consumed by the substring-quote-verifier (workspace C):
the doc and the claimed quote may be in different normalization forms; the
verifier must normalize before substring search, never after.

## Format

`nfc_nfd_pairs.json` — schema version `v2-adversarial-unicode-pairs-2026-04-29`.

Each entry under `pairs[]`:

| field | meaning |
|---|---|
| `id` | stable handle for this pair (used in test parameter ids) |
| `language_name` | human-readable language |
| `iso_lang` | ISO-639-1 two-letter code (matches `Quote.source_lang`) |
| `context` | what this string represents in a real OLAF case file |
| `nfc` | NFC-composed form, encoded with `\uXXXX` escapes — bytes are unambiguous |
| `nfd` | NFD-decomposed form, same content, different code-point sequence |
| `nfc_codepoints` / `nfd_codepoints` | per-code-point breakdown (or `_summary` for longer strings) |
| `decomposed_marks` | which combining marks appear in NFD form |
| `nfc_utf8_byte_length` / `nfd_utf8_byte_length` | UTF-8 byte counts; **always different** |
| `nfc_utf8_sha256` / `nfd_utf8_sha256` | SHA-256 of UTF-8 bytes; **always different** |
| `notes` | OLAF-relevant context for why this pair matters in practice |

## Invariants

For every entry:

1. `nfc != nfd` as Python strings (different code-point sequences).
2. `unicodedata.normalize("NFC", nfd) == nfc` (canonically equivalent).
3. `unicodedata.normalize("NFD", nfc) == nfd`.
4. `nfc.encode("utf-8") != nfd.encode("utf-8")` (raw bytes differ).
5. The recorded `*_utf8_byte_length` and `*_utf8_sha256` reflect the bytes after
   JSON-decoding the `\uXXXX` escapes.

These invariants are enforced by the writer script that produces this file
(see "Source" below). Tests should re-assert them on load as a smoke check.

## Coverage

Seven language pairs (task spec asks for ≥5):

| id | language | what's decomposed |
|---|---|---|
| `ro_t_comma_a_breve` | Romanian | ț (comma below) + ă (breve) |
| `it_e_grave` | Italian | è (grave) |
| `fr_societe_generale` | French | é × 4 (acute) |
| `bg_toyota` | Bulgarian | й (breve over Cyrillic и) |
| `el_proti` | Greek | ώ (tonos / acute) |
| `de_mueller` | German | ü (diaeresis) — bonus |
| `es_espana` | Spanish | ñ (tilde) — bonus |

## Source

Hand-crafted. All strings are common, non-confidential words (country names,
generic surnames, common verbs, public bank names). No content lifted from any
case file — synthetic fixtures only. The choice of words reflects what tends to
appear in OLAF anti-fraud case docs: bank names, country names, common surnames,
phrasings drawn from witness testimony.

The bytes written to disk were produced by a Python helper that calls
`unicodedata.normalize` and then asserts the five invariants above before
`json.dump(..., ensure_ascii=True)`. If an entry is ever edited by hand,
re-run the assertions: a hand-edit can quietly collapse NFD into NFC because
most editors save in NFC.
