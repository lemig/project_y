---
name: narrate-fraud-pattern
version: v1
owner: m.cabero@olaf.eu
resolver: (?i)\b(narrat(?:e|ive|ion)|tell\s+the\s+story|write[\s\-]?up|1[\s\-]?page\s+(?:summary|narrative)|case\s+summary|summari[sz]e\s+the\s+(?:fraud|case|pattern|scheme|investigation))\b
output_schema_ref: schema.note.Note
verifier: verifier.substring_quote
tests_dir: skills/narrate-fraud-pattern/tests
---

# narrate-fraud-pattern

Pure-synthesis skill. Consumes a set of grounded investigation `Note`s
emitted by other skills (`find-money-flow`, `detect-procurement-collusion`,
`find-shell-companies`, `summarize-by-entity`, `flag-suspect-doc`,
`cross-reference-pep`) and assembles a single one-page narrative `Note`
that walks an analyst through the case as a chronological story.

This skill **does not** read source documents. It does not call the
substring quote verifier with new offsets. It re-uses the `exact_quotes`
of its input `Note`s verbatim, so every claim in the output narrative is
**transitively grounded** in the same document positions that the input
notes already passed through the verifier on their way in. The audit
trail is preserved by quote inheritance, not by re-derivation.

## Inputs

- `notes: tuple[Note, ...]` — the upstream evidence pool. Each input note
  already carries ≥1 `Quote` with full provenance (`doc_id`, page,
  char offsets, `extractor_version`, `normalized_text_sha256`,
  `source_lang`, `translator_of_record`).
- `brief: Brief` — the original investigation brief. Its `text` answers
  "what story is the analyst trying to read?" and its `corpus_snapshot_hash`
  pins the narrative to the same per-investigation snapshot the input
  notes were derived against.

## Output

Exactly **one** `Note`:

- `claim` — the headline of the narrative (≤ ~25 words). The "lede" in
  investigative-journalism terms: actors + mechanism + scale.
- `exact_quotes` — the union of input-note `Quote`s that the narrative
  actually leans on. Reproduce them byte-for-byte; do not paraphrase
  inside the `quote_text`. If multiple input notes cite the same
  `(doc_id, char_offset_start, char_offset_end)`, deduplicate on that
  triple — keep one Quote, not many.
- `confidence` — the **minimum** confidence across the input notes that
  this narrative quotes from. Never higher than the weakest evidentiary
  link; synthesis cannot manufacture certainty.
- `why_relevant` — one paragraph framing the narrative against the brief.
- `tier` — `"investigation"` (v3 will introduce a separate `mandate` tier).
- `source_corpus_snapshot_hash` — copy from the input notes (must all
  agree; refuse to synthesize across mismatched snapshots).
- `brief_hash` — `Brief.compute_hash(brief)`.
- `skill_id` — `"narrate-fraud-pattern@v1"`.
- `skill_resolver_match` — the substring of `brief.text` that fired the
  resolver regex above.
- `skill_version` — git SHA-1 of this `SKILL.md` at run time.

## Methodology

The narrative is structured around four columns drawn from the
investigative-journalism canon. Hunter (UNESCO 2011) calls these the
"who / how / why / so what" of a story-based inquiry; the ACFE Fraud
Examiners Manual frames the same content as the report's "executive
summary plus chronology of events" [ACFE §4.7xx — public table-of-contents
is on the ACFE website]; FATF (2012, "Operational Issues — Financial
Investigations Guidance," §III.B) describes the same artefact as the
"case narrative" produced after evidence consolidation.

### 1. Chronology (the spine)

Order events by their **document-attested date**, not by the order the
input notes were generated. If a note's claim references a date, that
date anchors the event; if multiple notes reference the same event,
fold them. Where dates are uncertain or only partially extractable
(e.g., "Q2 2023"), place the event in a clearly-labelled bucket and
say so in the prose. Do not invent dates to fill gaps.

This follows IRE's standard investigative-narrative pattern: "Find the
spine. The spine is the timeline."  (Investigative Reporters and Editors,
*The IRE Reporter's Handbook*, public training excerpts; CIJ/Centre for
Investigative Journalism *The Investigative Journalist's Handbook*,
chapter on narrative structure).

### 2. Actors (the dramatis personae)

For each entity referenced in the input notes — natural person, legal
entity, account, contract — record:

- canonical name as it appears in the source quote (verbatim);
- role in the alleged scheme (originator, intermediary, beneficiary,
  facilitator, gatekeeper);
- whether the entity was flagged by an upstream skill
  (`find-shell-companies`, `cross-reference-pep`).

Roles come from FATF's typologies of money laundering and corruption
networks (FATF GAFI public typology reports, e.g. "Specific Risk Factors
in Laundering the Proceeds of Corruption", 2012) and the OECD Foreign
Bribery Report (OECD 2014, public PDF). Both are explicit, public, and
methodologically neutral — no OLAF-internal categories.

### 3. Mechanism (the how)

Describe the alleged scheme in the language of public investigative
typologies, not OLAF-internal jargon. Useful public anchors:

- ACFE's Fraud Tree (Occupational Fraud and Abuse Classification System;
  schema is public on acfe.com): asset misappropriation, corruption,
  financial-statement fraud.
- OECD/UNODC anti-corruption guides on procurement-rigging (bid rotation,
  bid suppression, complementary bidding, market allocation; OECD 2009
  *Guidelines for Fighting Bid Rigging*, public PDF).
- FATF guidance on shell-company and trade-based money-laundering
  patterns (FATF *Trade-Based Money Laundering*, 2006/2020, public).

Each step in the mechanism description must be backed by a quote drawn
from an input note. Where the public typology supplies the framing label
("complementary bidding", "layering"), the framing label is fine to use
in the prose; the **factual** assertion ("Vendor X submitted a bid that
was 0.4% above Vendor Y's") must carry an inherited Quote.

### 4. Evidence (transitive grounding)

This is the hard rule. Every factual sentence in the narrative must be
followed by — or visibly attributable to — at least one Quote drawn
from the input notes. The Quote's `doc_id`, page, and char offsets are
copied unchanged. The `quote_text` is reproduced byte-for-byte; if it is
non-English, the `quote_text_en` and `translator_of_record` are also
copied unchanged. **Do not retranslate.** If an upstream note carries
`translator_of_record: "<id>:translation_failed"` and a `null`
`quote_text_en`, that null is preserved into the output Note's
`exact_quotes` exactly as-is — the audit log already recorded the
translation failure upstream and we do not silently paper over it here.

The output Note's confidence is the **minimum** across the inputs that
the narrative quotes from. This is the "weakest link" rule from
investigative-journalism practice (Hunter 2011, §"Hypothesis test"):
a story is no more reliable than its least-supported assertion.

## Anti-patterns (REJECT)

- **Re-fetching documents.** This skill consumes Notes and produces a
  Note. It must not call the document source. If the planner gives it
  no input notes, it returns no narrative; it does not fall back to
  document retrieval.
- **Paraphrasing inside `quote_text`.** Quotes are byte-exact, period.
  Paraphrasing belongs in `claim` and `why_relevant` and the surrounding
  prose — never inside a Quote.
- **Confidence inflation.** The synthesized Note's `confidence` is the
  minimum of the cited inputs. Synthesis cannot lift confidence above
  any single piece of underlying evidence.
- **OLAF-internal framing.** Use only public typology labels (ACFE,
  FATF, OECD, IRE). Do not introduce internal codes, case-handling
  language, or operational categorisations.
- **Cross-snapshot synthesis.** All input notes must share the same
  `source_corpus_snapshot_hash`. If they do not, refuse — log the
  mismatch and emit no narrative. Mixing snapshots silently destroys
  the per-investigation provenance.
- **Silent quote drop.** If an input note's quote is referenced in the
  prose but does not survive deduplication, the prose must be rewritten;
  do not leave a factual sentence with no surviving inherited Quote.

## References (public sources)

- Hunter, M. L. (2011). *Story-Based Inquiry: A Manual for Investigative
  Journalists*. UNESCO. (Open-access PDF; cited for narrative spine and
  hypothesis-test methodology.)
- Investigative Reporters and Editors (IRE). *The IRE Reporter's
  Handbook*; public training excerpts. (Narrative-structure heuristics.)
- Centre for Investigative Journalism (CIJ). *The Investigative
  Journalist's Handbook* (public chapters). (Narrative chronology.)
- ACFE. *Fraud Examiners Manual* (public TOC) and the Occupational
  Fraud and Abuse Classification System ("Fraud Tree"; public on
  acfe.com). (Mechanism typology.)
- FATF (2012). *Operational Issues — Financial Investigations Guidance*.
  Public PDF. (Case-narrative artefact definition.)
- FATF (2012). *Specific Risk Factors in Laundering the Proceeds of
  Corruption*; FATF *Trade-Based Money Laundering* (2006/2020). Public
  PDFs. (Actor-role typology and mechanism patterns.)
- OECD (2009). *Guidelines for Fighting Bid Rigging in Public
  Procurement*. Public PDF. (Procurement-collusion mechanism labels.)
- OECD (2014). *OECD Foreign Bribery Report*. Public PDF. (Actor-role
  typology in transnational corruption.)
- UNODC. *Anti-Corruption Toolkit* (public). (Mechanism framing for
  public-sector cases.)
