# Adversarial fixtures — near-quote inputs

## What this tests

The `near-quote-adversarial` hard-gated bug-class test (CLAUDE.md). The
substring quote verifier (workspace C) is the deterministic gate that prevents
the audit log from accepting hallucinated or "improved" quotes. Every entry
here is a near-miss: a `claimed_quote` that almost matches the document at the
`claimed_offsets`, but doesn't. The verifier MUST return a mismatch verdict
for all 20.

## Format

`cases.json` — schema version `v2-adversarial-near-quotes-2026-04-29`.

Each entry under `cases[]`:

| field | meaning |
|---|---|
| `id` | stable handle (used as test parameter id) |
| `category` | attack class — `off_by_one_char`, `whitespace`, `smart_quotes`, `ocr_confusion`, `offset_drift`, `case` |
| `doc_text` | the document body to verify against |
| `claimed_offsets` | `{start, end}` — the offsets the LLM/skill claims in the Note |
| `claimed_quote` | the verbatim quote text the LLM/skill claims |
| `doc_text_at_claimed_offsets` | the actual `doc_text[start:end]` slice — pre-computed for tests, asserted to differ from `claimed_quote` at fixture-build time |
| `expected_verdict` | always `"mismatch"` for these 20 cases |
| `what_attacker_did` | one-line description of the perturbation |
| `notes` | OLAF/OCR context: why this attack pattern appears in the wild |

## Coverage (20 cases)

| count | category | examples |
|---|---|---|
| 4 | `off_by_one_char` | missing letter, extra letter, substituted letter, transposed pair |
| 5 | `whitespace` | double space, NBSP, tab, line-feed, trailing space |
| 3 | `smart_quotes` | curly double quotes, curly apostrophe, em dash for hyphen |
| 6 | `ocr_confusion` | 0/O, 1/l, rn/m, cl/d, II/H, vv/w (the canonical OCR confusion pairs) |
| 1 | `offset_drift` | claimed text exists somewhere in the doc but offsets point elsewhere |
| 1 | `case` | verifier must not silently case-fold |

## Invariants asserted at fixture-build time

For every case: `doc_text[claimed_offsets.start:claimed_offsets.end] != claimed_quote`.
Tests should re-assert on load — if a hand edit ever makes a case actually match,
the entire test class becomes vacuous and we want to fail loudly.

## What the verifier should do

Per CLAUDE.md determinism rules:

1. Normalize both `doc_text` and `claimed_quote` to NFC.
2. Compare `doc_text[start:end]` to `claimed_quote` byte-for-byte after NFC.
3. If unequal → mismatch → 3-retry then drop+log per the audit-loss rule.
4. The verifier MUST NOT case-fold, strip whitespace, normalize smart quotes,
   or apply any OCR-correction heuristic at this layer. Those are upstream
   responsibilities — at the trust boundary the gate is "exact substring after
   NFC, full stop."

## Source

Hand-crafted, fully synthetic. Doc texts are short flavored sentences resembling
EU-procurement / KYC / bank-transfer wording but contain no real entities. Three
base docs: a transfer line, a contract line, a scanned-document line — chosen
to give the OCR-confusion attacks (0/O, 1/l, etc.) plausible carriers.
