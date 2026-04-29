---
name: summarize-by-entity
version: v1
owner: m.cabero@olaf.eu
resolver: (?i)\b(?:summari[sz]e|summary|profile|dossier|background|what\s+(?:do|did|have)\s+we\s+(?:know|learned?))\b.*?\b(?:about|on|of|for|each\s+entity|per\s+entity|by\s+entity|entit(?:y|ies))\b
output_schema_ref: schema.note.Note
verifier: verifier.substring_quote
tests_dir: skills/summarize-by-entity/tests
---

# summarize-by-entity

Per-entity summary across all documents in the corpus snapshot that mention
the entity. Produces one `Note` per resolved canonical entity, carrying a
chronologically ordered, deduplicated timeline of mentions with verbatim
quotes and full provenance. Pre-step for `narrate-fraud-pattern` and a
standalone "background dossier" output for analysts.

## When this skill fires

The planner routes a brief here when the analyst asks for a per-subject
synthesis ("summarize what we know about Acme Holdings", "build a dossier on
John Smith", "background on Banca Intesa", "summary by entity"). The
`resolver` regex captures both the synthesis verb (summarize, profile,
dossier, background, "what do we know") and a target preposition or entity
qualifier (about / on / of / for / each entity / by entity).

It does NOT fire on case-level synthesis briefs ("narrate the fraud
pattern", "summarize the case") — those route to `narrate-fraud-pattern`.

## Inputs (planner-supplied)

- `entity_query` — verbatim entity name from the brief (string, ≥1 char).
- `entity_aliases` — optional list of known aliases / transliterations /
  registry numbers / tax IDs to seed entity resolution.
- `corpus_snapshot_hash` — sha256 of the locked per-investigation snapshot
  (passed unchanged into every emitted `Note`).
- `brief_hash` — canonical sha256 of the parent `Brief` (passed unchanged).

## Method

The methodology is structured deduplication of mentions, ordered in time,
with verbatim provenance. Adapted from public investigative-journalism and
fraud-examination practice (see References).

1. **Resolve the entity.** Use the Aleph REST `/api/2/entities` and
   `/api/2/match` endpoints scoped to `corpus_snapshot_hash` to map
   `entity_query` (+ aliases) onto canonical Follow-the-Money entities.
   Carry through every alias the registry returns: alternate spellings,
   transliterations (Latin / Cyrillic / Greek), abbreviations, prior
   names, tax / VAT / company-registry numbers. Per FATF Recommendation 10
   and the FATF beneficial-ownership guidance, alias and identifier
   coverage is the dominant driver of recall in entity matching.

2. **Retrieve mentions.** For each canonical entity, query the snapshot
   for documents in which any alias appears (Aleph full-text +
   FtM-property hits). Bound the result set; if > 50 mentions, rank by
   mention salience (see step 6).

3. **Extract spans.** For each hit, pull the verbatim matching span plus
   one to two sentences of surrounding context, recording
   `(doc_id, page, char_offset_start, char_offset_end, extractor_version,
   normalized_text_sha256, source_lang)`. The substring quote verifier is
   the hard generation-time gate (see CLAUDE.md §5); on three consecutive
   verifier failures for a span, drop the span and log the reason.

4. **Translate.** When `source_lang != "en"`, attach an English
   translation as `quote_text_en` and set `translator_of_record` to
   `"<translator-id>@<version>"`. On translation failure, set
   `translator_of_record` to the exact suffix marker
   `"<translator-id>:translation_failed"` and leave `quote_text_en` as
   `null` (per CLAUDE.md §5; never silently drop the source quote).

5. **Deduplicate.** Collapse near-identical mentions:
   - identical `normalized_text_sha256`, OR
   - Jaro-Winkler similarity ≥ 0.95 on normalized text after stripping
     whitespace, punctuation, and case.
   When collapsing, prefer the earliest document by date, and union the
   set of `doc_id`s into the surviving quote's provenance comment in
   `why_relevant`. (The schema does not store a "merged-from" list; the
   audit log carries the full collapse trail.)

6. **Order chronologically.** Sort surviving mentions by document date,
   falling back in this order: explicit document date → filing /
   submission date → upload date → file mtime. Ties broken by `doc_id`
   ascending for determinism.

7. **Score salience.** When the mention count exceeds 50, retain the
   top 50 by:
   - mention in document title or party block (+3),
   - signatory / counterparty role (+2),
   - first-page mention (+1),
   - body-text mention (+0).
   Document the count and selection rule in `why_relevant`.

8. **Emit one `Note` per canonical entity.**
   - `claim` — `"Entity timeline for <canonical_name>: <n> mention(s)
     across <m> document(s), <d_start>..<d_end>"`.
   - `exact_quotes` — the deduplicated, chronologically ordered tuple
     of `Quote` objects from steps 3-6.
   - `why_relevant` — short prose describing the kinds of roles in which
     the entity appears (counterparty / director / signatory / shareholder
     / beneficiary / referenced third party), plus any salience-truncation
     note from step 7.
   - `confidence` — `min(1.0, 0.4 + 0.1 * unique_doc_count)`, capped at
     `0.5` if the entity matched on a single alias and no FtM canonical
     existed prior to resolution. (The verifier is the hard gate; this
     score is advisory ranking only.)
   - `tier` — `"investigation"` (mandate-tier deferred to v3 per
     CLAUDE.md §7).
   - `source_corpus_snapshot_hash`, `brief_hash`, `skill_id`,
     `skill_version`, `skill_resolver_match` — passed through.

## Failure modes

- **Entity not found.** Emit no `Note`. Log
  `summarize-by-entity:entity-not-resolved` with the queried text and the
  list of aliases consulted.
- **Multiple canonical matches** ("Acme Corp Ltd" vs "Acme Corp Inc").
  Emit one `Note` per canonical; never silently merge across canonicals.
- **Single-mention entity.** Still emit; cap `confidence ≤ 0.5`.
- **All quotes fail the substring verifier.** Drop the `Note` (the schema
  requires `≥1` quote). Log
  `summarize-by-entity:all-quotes-rejected` with per-quote reasons. No
  silent loss (CLAUDE.md §5).
- **Translation outage.** Continue producing the `Note` with source
  quotes only and the `:translation_failed` marker on each affected
  quote.

## Output contract

`tuple[Note, ...]` — exactly one `Note` per resolved canonical entity.
Each `Note` validates against `schema.note.Note` and carries ≥ 1 `Quote`
that the substring quote verifier accepts.

## References

These references are public investigative methodology only (per
CLAUDE.md "Critical rules": no OLAF-internal procedures in skills).

- Mark Lee Hunter (ed.), *Story-Based Inquiry: A Manual for Investigative
  Journalists*, UNESCO, 2011 — chapters on "character files" and
  organising evidence by subject.
- Brant Houston, Len Bruzzese & Steve Weinberg, *The Investigative
  Reporter's Handbook*, 5th ed., Bedford/St. Martin's, 2009 — chapters on
  backgrounding people and organisations.
- Association of Certified Fraud Examiners (ACFE), *Fraud Examiner's
  Manual*, Investigation section, "Background Investigations" and
  "Tracing and Recovery of Assets" (current edition).
- Financial Action Task Force (FATF), *Guidance on Beneficial Ownership
  for Legal Persons*, March 2023 — entity-resolution and alias coverage
  patterns.
- FATF, *International Standards on Combating Money Laundering and the
  Financing of Terrorism & Proliferation* (the FATF Recommendations),
  Recommendation 10 (Customer Due Diligence) — minimum identifying
  attributes for legal persons.
- OECD, *Bribery and Corruption Awareness Handbook for Tax Examiners and
  Tax Auditors*, OECD Publishing, 2013 — building subject profiles from
  fragmented records.
- OCCRP, *Investigative Dashboard / Aleph User Guide* (public training
  materials) — practical patterns for collecting per-subject evidence
  across heterogeneous corpora.
- Centre for Investigative Journalism (CIJ), *The Investigative
  Journalist's Toolkit* (public training resources) — subject dossier
  workflow.
