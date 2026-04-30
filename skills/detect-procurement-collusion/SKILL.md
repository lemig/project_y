---
name: detect-procurement-collusion
version: v1
owner: miguel.cabero@ec.europa.eu
resolver: (?i)\b(bid[\s-]?rigg(?:ing|ed)|tender[\s-]?(?:rigg(?:ing|ed)|collusion)|(?:procurement|tender|public[\s-]contract)[\s-]?(?:fraud|collusion|rigging|cartel)|collusive[\s-]+(?:bid|bidder|bidding|tender(?:ing)?)s?|(?:cover|complementary|courtesy|phantom|suppressed?)[\s-]+bid(?:ding|s|ders?)?|bid[\s-]+rotation)\b
output_schema_ref: schema.note.Note
verifier: verifier.substring_quote
tests_dir: skills/detect-procurement-collusion/tests
---

# detect-procurement-collusion — Methodology (v1, public sources only)

## Purpose

Given a procurement brief and a corpus of tender documents (call for tenders, bids,
evaluation reports, award decisions, corporate registry extracts), identify
**signals of collusion among bidders or between bidders and the contracting
authority** and produce one Note per signal. Each Note's `claim` describes a
single signal; each `exact_quotes` entry pins the corroborating text to a real
document position so the substring quote verifier can hard-gate output.

**Strictly public methodology.** This skill is built from sources that are
distributable under EUPL v1.2 / Apache 2.0 publication. No OLAF-internal
operational details. The investigator decides escalation; the skill produces
quoted observations.

## Airgap behavior

OLAF's production environment is air-gapped. This skill is offline-first by
design:

- **Zero network I/O at runtime.** The skill reads documents from the
  per-investigation Aleph corpus snapshot (local) and emits Notes; it never
  fetches URLs.
- **Methodology is in this file.** The signals catalogue is encoded inline
  (sections A–D). External sources are *citations*, not runtime inputs.
- **Reference URLs.** The links in *Sources cited* below are pointers to
  where each source can be retrieved when online. Treat a dead link as a
  citation-hygiene issue, not a runtime failure.

## Sources cited (all public)

1. **OECD (2009, 2025 update).** *Guidelines for Fighting Bid Rigging in
   Public Procurement.* — the canonical public catalogue of bid-rigging
   schemes and warning signs.
   <https://www.oecd.org/en/publications/guidelines-for-fighting-bid-rigging-in-public-procurement_8cfeafbb-en.html>
   (2025 update:
   <https://www.oecd.org/en/publications/oecd-guidelines-for-fighting-bid-rigging-in-public-procurement-2025-update_cbe05a56-en.html>)
2. **ACFE.** *Fraud Examiners Manual* — Procurement Fraud Schemes
   (collusion among contractors; collusion between contractor and employee).
   <https://www.acfe.com/fraud-resources/fraud-101-what-is-fraud>
3. **World Bank (2013).** *Fraud and Corruption Awareness Handbook.*
   <https://documents.worldbank.org/curated/en/100851468152707470>
4. **U4 Anti-Corruption Resource Centre.** Publications on corruption risks in
   public procurement. <https://www.u4.no/publications>
5. **UNODC (2013).** *Guidebook on anti-corruption in public procurement and
   the management of public finances.*
   <https://www.unodc.org/documents/corruption/Publications/2013/Guidebook_on_anti-corruption_in_public_procurement_and_the_management_of_public_finances.pdf>
6. **FATF (2012, updated).** Recommendations on beneficial ownership transparency
   (relevant to common-ownership signals across bidders).
   <https://www.fatf-gafi.org/en/topics/beneficial-ownership.html>

## Signals to detect

The OECD catalogue (Source 1, pp. 4–8) groups bid-rigging schemes into four
families. The signals below combine those schemes with documentary red flags
from Sources 2–5 (procurement-corruption literature) and Source 6 (FATF
beneficial-ownership guidance). **Look for any of these. Each detected
signal is one Note.**

### A. Bid suppression, complementary bidding, bid rotation, market allocation (OECD §2)

1. **Round-robin / rotation.** The same small set of firms wins successive
   tenders in turn while the others submit losing bids. *Documentary trace:*
   award decisions over time list the same firms cycling as winners, with the
   same losing cast.
2. **Complementary (cover / courtesy / phantom) bidding.** Losing bids are
   designed not to win — prices well above the winning bid and above any
   reasonable market estimate; bids missing required documents; bids
   withdrawn after the deadline; bids that copy the call's specification
   verbatim with no engineering of their own. (OECD pp. 4–5; ACFE Fraud
   Examiners Manual, "Collusion Among Contractors".)
3. **Bid suppression.** A previously active bidder declines to submit, with
   correspondence showing coordination with another bidder.
4. **Subcontracting to the loser.** The winning bidder subcontracts material
   work back to a losing bidder — economically inconsistent with genuine
   competition (OECD p. 7; World Bank Handbook §IV).

### B. Suspicious bid timing and submission patterns

5. **Last-minute submission clusters.** All "competing" bids arrive in the
   last hour of the window from the same courier, IP, fax line, or postmark.
6. **Identical clerical errors / typos / formatting across bids.** Same
   misspelling, same odd page break, same metadata author, same template
   header — strong indicator that bids were drafted in one place. (OECD
   p. 6 "Suspicious documents"; ACFE manual.)
7. **Bids submitted in identical envelopes, with sequential serial numbers,
   in the same handwriting, or with the same postage meter mark.** (OECD
   p. 6.)
8. **Round-number bids that fall just under a notification or audit
   threshold.** (UNODC §3.4; World Bank Handbook §IV.)

### C. Common ownership / undisclosed relationships among "competing" bidders

9. **Shared registered address, phone number, email domain, bank account,
   or notary across "independent" bidders.** (FATF Recommendation 24
   on beneficial-ownership transparency; OECD p. 7.)
10. **Common directors, shareholders, or ultimate beneficial owners** across
    bidders — verifiable from corporate-registry extracts in the corpus.
11. **One bidder is a recent shell** (registration date weeks before the
    tender; minimal capital; no track record) **owned or staffed by another
    bidder's principals.** (FATF guidance on shell companies; UNODC §4.)

### D. Tailored / restrictive specifications and procedural irregularities (OECD §3, World Bank §III)

12. **Unusually narrow technical specifications** that match exactly one
    bidder's product/credentials — brand-name lock-in, proprietary
    certifications only one firm holds, qualification requirements written
    in terms only one firm meets.
13. **Last-minute spec changes** issued via amendment that disqualify
    competitors but not the eventual winner.
14. **Unjustified single-source / direct-award justification** ("only one
    supplier can do this") not supported by a documented market survey.
15. **Bid evaluation criteria that include vague subjective categories with
    high weight,** especially when scoring records show all evaluators
    converging on the same outlier-high score for the eventual winner.

## Output: one Note per detected signal

For each signal you detect, emit a single `Note` with:

- `claim`: a one-sentence description of the signal, naming the entities and
  documents involved. **Describe what the documents say, not what it proves.**
  Example: "Bidders Acme Srl and Beta Srl share registered address Via Roma 12,
  Milano, per ANAC procurement file p. 3 and Camera di Commercio extracts."
- `exact_quotes`: ≥1 `Quote`, each pinned to its `(doc_id, page,
  char_offset_start, char_offset_end)` so the substring verifier passes.
  When the same signal spans documents (e.g. shared address visible in two
  registry extracts), include one Quote per document.
- `confidence`: float in [0, 1]. Calibrate against the OECD signal strength
  table:
  - 0.9–1.0 — direct documentary evidence (e.g. identical wire-transfer
    metadata between "competing" bidders, signed coordination email).
  - 0.7–0.9 — strong structural signal (common UBO across bidders;
    identical clerical errors).
  - 0.4–0.7 — suggestive but ambiguous (round-number bids; narrow specs).
  - <0.4 — do not emit a Note. Drop and log the reason.
- `why_relevant`: one-to-two sentences linking this signal to the brief.
  Reference the OECD scheme family (A/B/C/D) so reviewers can map back.
- `tier`: always `"investigation"` for v2 (mandate-tier deferred to v3).

## Quote provenance — non-negotiable

Per CLAUDE.md (locked schema):

- `quote_text` is **verbatim source-language text**, NFC-normalized, not
  paraphrased. Substring verifier rejects mismatches; the harness retries up
  to 3× then drops the Note and writes an audit-log entry. **Silent loss is
  unacceptable** — every drop logs the reason.
- For non-English source documents, populate `quote_text_en` with an English
  translation and set `translator_of_record` to the translator id-and-version
  string (`<id>@<version>`). On translation failure set
  `translator_of_record` to `<id>@<version>:translation_failed` and leave
  `quote_text_en` as `null`. Continue — do not drop the Note for translation
  failures alone.
- ≈80% of OLAF cases are non-English. Expect Italian, French, Romanian,
  Bulgarian, Polish, German, Greek, Spanish source-language documents.
  Quote selection must use source-language text first, English second.

## What this skill does NOT do

- It does **not** allege fraud, criminal liability, or breach of competition
  law. It surfaces documentary signals from the corpus. Investigators decide
  what to do with them.
- It does **not** call external corporate-registry APIs. It works only with
  documents already inside the corpus snapshot. (Cross-referencing
  beneficial-owner sanctions is `cross-reference-pep`'s job.)
- It does **not** rank or compare procurements. Per-document, per-signal
  output only — narrative assembly is `narrate-fraud-pattern`'s job.
- It does **not** invoke any LLM in the trust path. The substring verifier
  + FtM validators + audit log writer + Aleph REST client remain pure
  deterministic Python (CLAUDE.md, premise 4).

## Stop conditions

- Brief does not match the resolver regex → skill is not loaded.
- Corpus contains zero procurement-shaped documents (no call-for-tenders,
  bids, or award decisions detectable by FtM `Project` / `Contract` /
  `ContractAward` schemata) → emit zero Notes; the planner logs the
  no-applicable-corpus reason.
- Per-signal confidence < 0.4 → drop, log reason in audit trail, do not
  emit.
