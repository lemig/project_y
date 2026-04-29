---
name: find-shell-companies
version: v1
owner: m.cabero@olaf.eu
resolver: (?i)\b(shell|front|letterbox|mailbox|fictitious|nominee|UBO|beneficial[\s-]+owner(?:ship)?s?|opaque[\s-]+owner(?:ship)?s?|hidden[\s-]+owner(?:ship)?s?|mass[\s-]+incorporat(?:ion|ed)|registered[\s-]+agent)\b
output_schema_ref: schema.note.Note
verifier: verifier.substring_quote
tests_dir: skills/find-shell-companies/tests
---

# find-shell-companies

Score each entity in the corpus for shell-company likelihood from registration
patterns and ownership opacity, and emit one `Note` per scored entity carrying
the score breakdown plus verbatim quote evidence for every indicator that fired.

This skill is purely investigative ranking. It does not assert a legal
conclusion ("X is a shell company"); it surfaces structural red flags that an
analyst can corroborate. Every claim is grounded in a quote anchored to a real
document offset; the substring quote verifier is the hard gate.

## When this skill fires

The planner routes a brief to this skill when the resolver regex matches —
typical brief language: "find shell companies", "screen for letterbox /
mailbox entities", "look for nominee directors", "check for opaque beneficial
ownership", "identify front companies", "are any of these vendors shells".

## Indicator framework (5 indicators, 1 point each, 0–5)

The framework mirrors the structural red flags described in the public
literature on the misuse of corporate vehicles. Cited sources at the bottom of
this file. Each indicator either fires (1) or does not (0); the total drives
confidence. **Every indicator that fires must be backed by at least one
verbatim quote from a corpus document, with full provenance.** No indicator
fires on inference alone.

### I1 — High-secrecy / mass-incorporation jurisdiction

The entity is registered in a jurisdiction that the FATF, OECD, and StAR
literature flag as commonly misused for opaque corporate structures. A
non-exhaustive starting set (verify against the live FATF / EU lists at
investigation time, not from this file):

- British Virgin Islands, Cayman Islands, Bermuda, Bahamas, Anguilla,
  Turks & Caicos
- Panama, Belize, Nevis, St. Kitts & Nevis, St. Vincent & the Grenadines
- Seychelles, Mauritius, Marshall Islands, Vanuatu, Cook Islands, Samoa
- Delaware, Wyoming, Nevada (U.S. LLC pass-throughs with thin disclosure)
- Hong Kong, Singapore (when paired with other indicators — these are major
  legitimate financial centres; do not fire on jurisdiction alone here
  without I2/I3/I4/I5 corroboration)

Quote requirement: a registration document, certificate of incorporation, or
contract recital naming the jurisdiction.

### I2 — Young entity (incorporation date within ≤ 12 months of the relevant transaction or contract)

Newly-incorporated entities transacting at scale, especially as suppliers in
public procurement or as recipients of large transfers, are a recurring
indicator across the Panama Papers / Pandora Papers / FinCEN Files corpora.

Quote requirement: incorporation date AND a contemporaneous transaction /
contract date both quoted from corpus documents; the offset between them is
≤ 12 months.

### I3 — Shared registered address (mass-incorporation agent / virtual office)

The registered office address is shared with many other entities — typically
the address of a registered-agent / company-formation service, a virtual
office, or a "letterbox" address. Public investigations have flagged
addresses such as 1209 North Orange Street (Wilmington, DE), Trident Trust
offices, Mossack Fonseca / Alemán Cordero / Asiaciti chains; modern
equivalents change over time.

Quote requirement: the registered address from a registry / contract /
filing in the corpus AND evidence (also in the corpus, or by cross-reference
across two or more corpus entities) that the same address recurs across
otherwise-unrelated entities. **If the cross-reference evidence is not in
the corpus, do not fire I3** — record the suspicion in `why_relevant` only,
do not award the point.

### I4 — Nominee directors / nominee shareholders

A director or shareholder is explicitly described as a "nominee", or appears
as the named director/shareholder of an unusually large number of otherwise-
unrelated entities in the corpus, or holds the position alongside a
disclosed power-of-attorney that delegates control elsewhere.

Quote requirement: a verbatim quote naming the director/shareholder AND the
"nominee" wording, or AND the multi-entity cross-reference (same individual
appearing as director in N≥3 other corpus entities).

### I5 — Undisclosed or evasive UBO (ultimate beneficial owner)

The UBO field is blank, marked "to be confirmed", names another corporate
vehicle (chained through ≥2 layers without reaching a natural person), or
the disclosed UBO is itself a non-cooperative entity in a high-secrecy
jurisdiction (compounding I1).

Quote requirement: the UBO field as it appears in the corpus document
(KYC questionnaire, beneficial-ownership filing, due-diligence report).

## Output

For each entity that scores ≥ 1, emit exactly one `Note` shaped per
`schema.note.Note`. The skill MUST NOT emit a Note for entities that score 0.

- `claim` — single sentence of the form
  `"<EntityName> scores <N>/5 on shell-company indicators: <fired-indicator-codes>."`
  Example: `"ACME Holdings Ltd scores 4/5 on shell-company indicators: I1, I2, I3, I5."`
- `exact_quotes` — one or more `Quote` per indicator that fired (≥ N quotes
  total). Source-language verbatim; `quote_text_en` populated for non-EN
  sources; `translator_of_record` always set when `source_lang != "en"`. On
  translation failure, set `translator_of_record` to
  `"<translator-id>:translation_failed"` (exact suffix) and leave
  `quote_text_en` null — never silently drop the indicator.
- `confidence` — derived deterministically from the score:
    - 5/5 → 0.95
    - 4/5 → 0.80
    - 3/5 → 0.65
    - 2/5 → 0.45
    - 1/5 → 0.25
- `why_relevant` — explain how the indicators tie to the brief
  (e.g., "supplier in the contract under investigation; combined I1+I2+I3
  pattern matches the FATF letterbox-company red flag set"). Note here any
  suspicion that did NOT fire because the corroborating evidence is outside
  the corpus snapshot.
- `tier` — `"investigation"` (mandate tier deferred to v3 per CLAUDE.md).
- `source_corpus_snapshot_hash`, `brief_hash`, `skill_id`,
  `skill_resolver_match`, `skill_version` — populated by the harness, not by
  the skill body.

## Hard rules

- **No silent loss.** If a candidate indicator looks plausible but the
  corroborating quote cannot be located in the corpus, do NOT fire the
  indicator and DO record the gap in `why_relevant`. Never emit an
  unverifiable claim and never drop the entity from output without a logged
  reason.
- **No legal conclusion.** Score and quote — do not write
  "X is a shell company". The Note exists so an analyst can decide.
- **Public methodology only.** This skill cites only ICIJ, FATF, OECD,
  StAR, ACFE, and other public sources. Do not encode any
  agency-internal investigative procedures, address blacklists, or
  case-derived heuristics in this file. Per CLAUDE.md, agency-internal
  operational details stay out of skills.
- **Multilingual.** ~80% of OLAF cases are non-English. When the source
  document is non-English, the verbatim quote stays in source language and a
  translation is provided alongside; English-only narration is unacceptable.

## Sources (public methodology)

1. **FATF (2023).** *Guidance on Beneficial Ownership of Legal Persons*
   (R.24, March 2023 revision). FATF/OECD, Paris.
   https://www.fatf-gafi.org/
2. **FATF / Egmont Group (2018).** *Concealment of Beneficial Ownership*.
   Joint report on the techniques used to obscure beneficial ownership,
   including nominees, complex layering, and high-secrecy jurisdictions.
3. **van der Does de Willebois, Halter, Harrison, Park, Sharman (2011).**
   *The Puppet Masters: How the Corrupt Use Legal Structures to Hide Stolen
   Assets and What to Do About It.* StAR Initiative, World Bank / UNODC.
4. **OECD (2018).** *Behind the Corporate Veil: Using Corporate Entities for
   Illicit Purposes* (and the OECD Anti-Bribery Convention working-group
   guidance on corporate-vehicle red flags).
5. **ICIJ.** Panama Papers (2016), Paradise Papers (2017), Pandora Papers
   (2021), FinCEN Files (2020) — public methodology notes on
   shell-company indicators (mass-incorporation agents, registered-address
   recurrence, nominee chains).
6. **ACFE.** *Fraud Examiners Manual* — Shell Company section under
   procurement / vendor fraud.
7. **EU Anti-Money-Laundering Directive (Directive (EU) 2018/843, 5AMLD)**
   and the **EU AML Authority (AMLA) Regulation (EU) 2024/1620** — beneficial
   ownership register requirements; structural baseline for what
   "non-disclosure" means in an EU corpus.

These citations are intentionally to public, citable, non-OLAF sources so the
skill is portable across the OLAF anti-fraud collaboration network and so
it remains compatible with whichever Commission-authorised license applies
at publication (EUPL v1.2 or Apache 2.0; decided at publication time per
CLAUDE.md).
