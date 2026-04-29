---
name: flag-suspect-doc
version: v1
owner: m.cabero@olaf.eu
resolver: (?is)(?=.*\bdoc(?:ument)?s?\b)(?=.*\b(?:suspect(?:ed)?|suspicious|risky|high[-\s]risk|fraud(?:ulent)?|fraud[-\s]?likelihood|anomal(?:ous|y|ies)|red[-\s]flag(?:ged|s)?)\b).*
output_schema_ref: schema.note.Note
verifier: verifier.substring_quote
tests_dir: skills/flag-suspect-doc/tests
---

# flag-suspect-doc

Rank documents in a corpus by fraud likelihood and emit one `schema.note.Note`
per ranked document, where the Note's claim is the fraud-likelihood judgement
and `exact_quotes` carry the verbatim text passages that justify it.

This skill preserves the v1 (project_x) primitive — fraud-flagging at the
document level — re-implemented under the v2 audit contract: every claim is
backed by a quote whose document position is verifiable by the substring
quote verifier, and every non-English quote carries a translator-of-record.

## When this skill fires

The `resolver` regex routes a brief here when it asks to rank, score, flag,
surface, find, identify, or list documents in connection with one of:
fraud, fraudulent, fraud-likelihood, suspect, suspicious, risky, high-risk,
anomalous, anomaly, anomalies, red flag, red-flagged.

Examples that fire:
- "Rank these documents by fraud likelihood."
- "Flag suspect documents in the 2023 procurement corpus."
- "Which documents look most suspicious in the Acme tender?"
- "Find documents with high fraud risk relating to vendor X."

Examples that do NOT fire (route elsewhere):
- "Trace the money flow from Account A to Account B." → `find-money-flow`
- "Summarize all documents mentioning Acme Corp." → `summarize-by-entity`
- "Translate the Italian invoices into English." → translation utility, not an
  investigative skill.

## Output contract

For each candidate document the skill emits exactly one `Note` with:

- `claim` — a one-sentence fraud-likelihood judgement on this document
  (e.g., "Invoice INV-2023-118 shows three independent procurement-fraud
  red flags: round-number total, vague service description, and a
  counterparty in a FATF-monitored jurisdiction.")
- `confidence` — a real value in [0, 1]; see scoring rubric below.
- `why_relevant` — one sentence explaining how this document advances the
  brief's investigation.
- `exact_quotes` — at least one `Quote`, one per signal cited in the claim.
  Each quote must be a verbatim substring of the document's normalized
  extracted text, with `(doc_id, page, char_offset_start, char_offset_end,
  extractor_version, normalized_text_sha256, source_lang,
  translator_of_record)` populated. The substring quote verifier is the hard
  gate — claims whose quotes do not verify are dropped after a 3-attempt
  regeneration loop and the drop is logged with reason. Silent loss is
  forbidden (see `CLAUDE.md`).
- `tier` defaults to `"investigation"` (mandate-tier is v3).
- `skill_id`, `skill_resolver_match`, `skill_version`,
  `source_corpus_snapshot_hash`, `brief_hash` are filled by the harness.

## Methodology

This methodology is built strictly from PUBLIC investigative literature.
No OLAF-internal procedures are encoded here. Sources are cited inline and
listed at the bottom.

The skill scores each document on two layers of features. Both layers are
necessary: metadata anomalies are weak signals on their own (high false-
positive rate per Singleton & Singleton, ch. 6), and content signals without
contextual metadata (counterparty, jurisdiction, timing) are easy to
manufacture. Co-occurrence is what discriminates.

### Layer 1 — Document metadata signals

For each document, extract structured metadata (Aleph entity properties,
header parsing, FollowTheMoney schema fields where present) and look for:

1. **High-risk-jurisdiction counterparty.** A sender, receiver, beneficial
   owner, or place of registration in a jurisdiction on the FATF "High-Risk
   Jurisdictions subject to a Call for Action" list, the FATF "Jurisdictions
   under Increased Monitoring" list, or the EU list of non-cooperative
   jurisdictions for tax purposes. Treat the official lists as the ground
   truth — never invent a list. (FATF, 2024; EU Council, 2024.)
2. **Round-number transaction amounts.** Transfers in amounts that are
   suspiciously round (whole thousands, whole tens of thousands) — a long-
   documented money-laundering and bribery signal in FATF typologies and
   the OECD Foreign Bribery Report. (FATF Typologies; OECD, 2014.)
3. **Threshold-adjacent amounts ("structuring" / "smurfing").** Multiple
   transactions just below a regulatory reporting threshold (e.g., < EUR
   10,000 in EU AML cash-reporting context) from or to the same counter-
   party in a short window. (FATF Recommendation 10; FinCEN guidance on
   structuring.)
4. **Timing anomalies.** After-hours or weekend processing dates;
   transactions clustered immediately before period-end reporting cut-offs;
   invoice or contract dates that fall on public holidays in the
   counterparty's jurisdiction. (Kranacher & Riley, ch. 8.)
5. **Counterparty / business-purpose mismatch.** A counterparty whose
   registered business activity, sector, or size is incompatible with the
   nature or magnitude of the transaction (e.g., a single-employee
   "consulting" firm receiving multimillion-euro payments). (OECD, 2014;
   Wolfsberg AML Principles for Correspondent Banking.)
6. **Single-use or shell-shaped counterparty.** Counterparty with no
   independent web presence, recently incorporated, registered at a mass-
   incorporation address, or sharing a registered address with many
   unrelated entities — classical shell-company indicators. (FATF
   "Concealment of Beneficial Ownership", 2018.)

### Layer 2 — Document content signals

For each document, after OCR/text extraction, scan the body for:

1. **Vague service descriptions.** Line items or contract scopes phrased as
   "consulting services", "general advice", "facilitation fee",
   "introduction services", "market research" with no deliverable named.
   The OECD Foreign Bribery Report (2014) identifies vague service
   descriptions as one of the most common bribery indicators in invoices.
2. **Mentions of opaque jurisdictions in the document body.** References
   inside the text (not just metadata) to jurisdictions widely associated
   with bank secrecy or beneficial-ownership opacity, especially when
   used as a routing point that has no apparent business rationale.
   (FATF; Tax Justice Network Financial Secrecy Index — public.)
3. **Use of intermediaries with no apparent role.** Agents, consultants,
   or sub-agents inserted into a transaction chain whose function is not
   explained in the document and whose remuneration is disproportionate
   to any stated activity. (OECD, 2014.)
4. **Inconsistencies between document type and content.** A purchase
   order that describes a service rather than goods; an invoice with no
   tax identifier where one is legally required; a contract with no
   counterparty signature block; mismatched dates between the document
   header and the body.
5. **Reused or templated language.** Identical wording across documents
   purportedly from independent counterparties (a strong signal that
   one party is drafting both sides of a transaction). (ACFE Fraud
   Examiners Manual.)
6. **Cash-equivalent and informal-value-transfer terminology.** Mentions
   of cash payments at thresholds normally settled by wire, references
   to informal-value-transfer systems where they are not the customary
   channel for the counterparty's region or sector. (FATF Hawala and
   Other Similar Service Providers report, 2013.)

### Scoring rubric

For each document, count how many distinct Layer-1 and Layer-2 signals fire,
and weight as follows. (These weights are a defensible default; tune via the
golden-run replay tests, never silently.)

- Each Layer-1 signal contributes 0.10 to the raw score.
- Each Layer-2 signal contributes 0.10 to the raw score.
- A document that fires at least one Layer-1 AND at least one Layer-2
  signal receives an additional 0.10 co-occurrence bonus.
- Cap raw score at 1.0.

Map raw score to the Note's `confidence` field directly. A document scoring
0.0 produces no Note (nothing to claim). A document scoring > 0 produces a
Note whose `claim` enumerates the specific signals fired and whose
`exact_quotes` field carries one quote per signal cited.

### Quote selection

For each cited signal, select the **shortest verbatim span** of the
document's extracted text that demonstrates the signal. Shorter quotes
reduce verifier brittleness (OCR noise, line-break placement) without
weakening the audit trail — the (doc_id, char offsets, sha256) tuple
preserves full traceability regardless of length.

For non-English documents the quote MUST be in the source language,
with `quote_text_en` set to the English translation and
`translator_of_record` populated. On translation failure the skill MUST
emit the source-language quote with `quote_text_en = None` and
`translator_of_record = "<translator-id>:translation_failed"` (exact
suffix), per the Note schema invariant. Never drop the quote silently.

### What this skill must NOT do

- Do NOT score a document on a single signal where the signal is a generic
  word match ("consulting" alone, "Cyprus" alone). False-positive rates on
  single-token matches make those signals worthless without corroboration.
- Do NOT invent jurisdiction lists, threshold values, or counterparty
  records. Use only the OFFICIAL public lists named above (FATF, EU, OECD)
  and the document's own extracted text. If a list is unavailable at run
  time, log it and skip the corresponding signal — do not guess.
- Do NOT emit a Note whose claim references a signal not present in
  `exact_quotes`. Every claimed signal must be quoted.
- Do NOT include OLAF-internal heuristics, case-specific knowledge, or
  classified indicators in this skill. Those belong in operational tooling
  outside the open-source-publishable methodology.

## Sources

- ACFE, "Fraud Examiners Manual" (current edition). Association of Certified
  Fraud Examiners.
- FATF, "International Standards on Combating Money Laundering and the
  Financing of Terrorism & Proliferation — The FATF Recommendations" (most
  recent revision).
- FATF, "High-Risk Jurisdictions subject to a Call for Action" and
  "Jurisdictions under Increased Monitoring" (updated three times yearly,
  public).
- FATF, "Concealment of Beneficial Ownership" (2018).
- FATF, "The Role of Hawala and Other Similar Service Providers in Money
  Laundering and Terrorist Financing" (2013).
- OECD, "Foreign Bribery Report — An Analysis of the Crime of Bribery of
  Foreign Public Officials" (2014).
- Council of the European Union, "EU list of non-cooperative jurisdictions
  for tax purposes" (updated periodically, public).
- Wolfsberg Group, "Anti-Money Laundering Principles for Correspondent
  Banking" (most recent revision).
- M. Kranacher and R. Riley, "Forensic Accounting and Fraud Examination",
  Wiley (most recent edition).
- T. Singleton and A. Singleton, "Fraud Auditing and Forensic Accounting",
  Wiley (most recent edition).
- Tax Justice Network, "Financial Secrecy Index" (public, biennial).
- IRE / Investigative Reporters and Editors, training materials on
  document-driven investigations (public).
