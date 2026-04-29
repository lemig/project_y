---
name: find-money-flow
version: v1
owner: m.cabero@olaf.eu
resolver: (?i)\b(money[\s-]*flow|money[\s-]*trail|funds?[\s-]*flow|follow[\s-]+the[\s-]+money|trace[\s-]+(?:the[\s-]+)?(?:money|funds?|payments?|transfers?|wire(?:s)?|cash|capital)|trace[\s-]+(?:account|contract|invoice|iban)|wire[\s-]+trace|account[\s-]+to[\s-]+account|transaction[\s-]+chain)\b
output_schema_ref: schema.note.Note
verifier: verifier.substring_quote
tests_dir: skills/find-money-flow/tests
---

# find-money-flow

Trace funds across documents and entities, starting from a concrete anchor
(account / IBAN / contract / invoice / named party). Every hop along the
trail is recorded as one Note backed by ≥1 verbatim source-language quote
with full provenance — doc id, page, char offsets, normalized-text sha256,
source language, translator of record. The Note schema is the locked v2
audit contract; the substring quote verifier (separate module) is the hard
gate that drops any Note whose quotes don't match the source document
exactly.

## When this skill fires

The planner routes a brief here when the brief asks for a money trail
behind a concrete anchor — e.g. "trace the 120k from contract X",
"follow the money out of account IT60X0542...", "where did the funds
to Polaris Limited come from?". The `resolver` regex above lists the
phrasings; tests cover the eval.

## Methodology

This skill follows three pieces of public investigative methodology — no
OLAF-internal procedure is encoded here.

1. **Placement → layering → integration** — the standard ACFE money-laundering
   model. Every hop is classified into one of the three stages; chains
   that compress placement and layering into <72h with no economic
   substance are a layering signal (cited below).
2. **Transaction-graph traversal** — walk forward (outflows) and backward
   (inflows) from the anchor, treating each new counterparty as a fresh
   anchor. Cap depth at a per-investigation hop budget.
3. **Verbatim-quote provenance** — every claim is grounded in a quote
   that lives at known character offsets in a known source document.
   This is the discipline taught in IRE/CIJ "Follow the Money"
   workshops and the World Bank/UNODC StAR Asset Recovery Handbook.

### Step 1 — Anchor

Extract the starting point from the brief. Prefer in this order:

1. Account number / IBAN / SWIFT identifier.
2. Contract or tender reference.
3. Invoice / payment-order number.
4. Named legal or natural person.

When the brief offers only a name with synonyms, invoke the
`cross-reference-pep` placeholder (v2 stub) to disambiguate before
proceeding. Never start a trail off a name with character-confusion
ambiguity (e.g. Cyrillic/Latin lookalikes, "0/O") without a confirming
identifier in a separate document.

### Step 2 — Forward trace (outflows)

For each anchor, search the corpus for documents that:

- Reference the anchor (account / contract / party), AND
- Contain a transaction signal: at least three of {amount, currency,
  date, counterparty, instrument reference}.

For each match, emit ONE Note describing ONE hop:

- `claim`: "<source> transferred <amount> <currency> to <destination>
  on <date> per <instrument> (doc <ref>)" — concise, factual.
- `exact_quotes`: ≥1 verbatim quote anchoring every factual element of
  the claim. Source-language `quote_text` is mandatory; for non-English
  sources `quote_text_en` carries an EN translation and
  `translator_of_record` names the translator (see CLAUDE.md note 6).
  When translation fails, the exact-suffix marker
  `<translator-id>:translation_failed` is set and `quote_text_en` is
  null (no silent loss).
- `why_relevant`: how this hop connects to the brief's question.
- `confidence`: 1.0 only when source, destination, amount, currency,
  AND date are all named in a single quote. Lower (0.7-0.9) when one
  element is inferred from a separate confirming quote in the same
  document. Lower still (≤0.6) when any element is inferred from
  another document.

### Step 3 — Backward trace (inflows)

Symmetric to step 2 but searching for inflows TO the anchor. Same Note
shape, direction reversed.

### Step 4 — Recurse on new endpoints

Each emitted hop produces a new endpoint (counterparty account or party).
Apply steps 2-3 to that endpoint until a stop condition fires.

### Step 5 — Stop conditions

Stop expanding a branch when ANY of the following holds:

1. **Trail cold** — the snapshot contains no documents referencing the
   new endpoint.
2. **Destination of interest** — the endpoint matches a flagged class
   (final beneficiary, cash-out point, asset purchase, sanctioned
   entity, PEP per `cross-reference-pep`). Emit a final Note labelling
   the destination class.
3. **Layering signal** — three or more rapid pass-through hops where
   each endpoint holds funds for less than one working day with no
   apparent economic substance, per FATF Methodology layering
   indicators. Emit a Note flagging the layering pattern; do not
   chase further hops on that branch.
4. **Hop budget exhausted** — default 8 hops per branch, configurable
   via the brief. Emit a Note recording the budget exhaustion and the
   last endpoint reached, so the human reviewer can extend manually.

### Step 6 — Output discipline

- One hop = one Note. Do not collapse multiple hops into a single Note.
- Verbatim quotes only. No paraphrase. The substring quote verifier
  drops Notes whose quotes are not exact substrings of the normalized
  source text; on three retries the Note is dropped and the drop
  reason is logged (CLAUDE.md "no silent loss in the audit log").
- Do NOT translate amounts, currencies, or identifiers — emit them
  verbatim and let the reviewer normalize.
- Do NOT infer a hop from entity co-occurrence alone; co-occurrence
  is not a transaction.

## Public-source citations

- ACFE, *Fraud Examiners Manual*, 2024 ed., Money Laundering section
  (placement / layering / integration).
- FATF, *International Standards on Combating Money Laundering and the
  Financing of Terrorism & Proliferation* (2012, updated 2023),
  Recommendations 10 (CDD) and 24-25 (beneficial ownership).
- FATF, *Methodology for Assessing Compliance with the FATF
  Recommendations*, Immediate Outcomes 4-5 (tracing).
- World Bank / UNODC StAR Initiative, *Asset Recovery Handbook: A
  Guide for Practitioners*, 2nd ed., 2021, ch. 4 (financial profile
  and tracing).
- Investigative Reporters & Editors (IRE) and the Centre for
  Investigative Journalism (CIJ), *Follow the Money* training
  curriculum (public).
- OECD, *Bribery and Corruption Awareness Handbook for Tax Examiners
  and Tax Auditors*, 2013, indicators of bribery payments.
- Wolfsberg Group, *Statement on AML Screening, Monitoring and
  Searching*, 2017 (transaction monitoring patterns).
