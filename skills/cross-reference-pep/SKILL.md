---
name: cross-reference-pep
version: v1
owner: m.cabero@olaf.eu
resolver: (?i)\b(pep|peps|politically[-\s]exposed[-\s]person(s)?|sanctions?|sanction[-\s]list|sanctions[-\s]screening|watch[-\s]?list|watchlist|adverse[-\s]media|kyc|cdd|edd|due[-\s]diligence|screen(ing)?|opensanctions|wolfsberg|fatf|beneficial[-\s]owner(s)?|ubo|director(s)?|officer(s)?|shareholder(s)?|counterpart(y|ies)|client(s)?|individual(s)?|natural[-\s]person(s)?|legal[-\s]person(s)?|company|companies|corporation(s)?|entit(y|ies))\b
output_schema_ref: schema.note.Note
verifier: verifier.substring_quote
tests_dir: skills/cross-reference-pep/tests
---

# cross-reference-pep — Entity → public PEP / sanctions screening

> **v2 status: PLACEHOLDER.** This skill flags entities that warrant
> PEP / sanctions screening but does **not** perform an actual lookup.
> v3 (deferred) wires in the OpenSanctions bulk index — same skill
> contract, same output schema, same audit trail; only the resolver step
> grows a live data path.

## What this skill does (v2)

For each candidate entity (natural person or legal person) named in the
investigation corpus, emit one `Note` with `claim` of the form:

> Entity "<name>" requires PEP / sanctions screening before any
> investigative conclusion that depends on its risk profile.

The Note is **a flag**, not an answer. It marks an entity for follow-up.
Every flag carries ≥1 `Quote` that pins the entity mention to a real
document position (doc_id, page, char_offset_start, char_offset_end),
because the substring verifier is a hard generation-time gate (CLAUDE.md
rule 5) and silent loss is unacceptable (CLAUDE.md rule, "no silent loss
in the audit log").

## Why this skill exists

Anti-fraud investigations routinely involve counterparties, beneficial
owners, signatories, and politically connected intermediaries. Failing
to screen them against PEP and sanctions sources produces two distinct
failure modes:

1. **False negatives** — a sanctioned actor passes through unflagged.
2. **Audit-trail gaps** — even when an investigator screens informally,
   the screening step is not recorded, and a downstream reviewer cannot
   tell whether it was done.

Both are addressed by emitting an explicit Note for every screen-worthy
entity. In v2 the Note documents the *requirement* to screen; in v3 it
will additionally document the *result* of the screen.

## Public methodology this skill follows

This skill encodes only public methodology. No OLAF-internal procedure
is documented here.

### What counts as a PEP

The Financial Action Task Force ("FATF") defines a PEP in **FATF
Recommendation 12 and its Interpretive Note** (FATF Recommendations,
*International Standards on Combating Money Laundering and the Financing
of Terrorism & Proliferation*, latest update Nov 2023):

- **Foreign PEPs** — individuals who are or have been entrusted with
  prominent public functions by a foreign country (e.g. heads of state,
  senior politicians, senior government / judicial / military officials,
  senior executives of state-owned corporations, senior political-party
  officials).
- **Domestic PEPs** — same categories, by a domestic country.
- **International-organisation PEPs** — persons entrusted with a
  prominent function by an international organisation (e.g. directors,
  deputy directors, members of the board).
- **Family members and close associates ("RCAs")** — extended status
  applies, on a risk-sensitive basis.

The **Wolfsberg Group "Guidance on Politically Exposed Persons" (2017)**
adds practitioner detail — in particular that a one-size definition is
inadequate and that PEP risk should be tiered (e.g. heads of state vs.
mayors of small municipalities) and time-bounded (former PEPs decay in
risk on a risk-sensitive basis but do not necessarily decay to zero).

### What counts as a sanctioned entity

Sanctions are imposed by a list-issuing authority and published as
designations. The investigator-relevant authorities a v3 lookup would
consult include, at minimum:

- **United Nations Security Council Consolidated List** (UNSC sanctions
  regimes — the binding, globally-applicable baseline).
- **EU Consolidated Financial Sanctions List** ("CFSP").
- **OFAC Specially Designated Nationals and Blocked Persons List**
  ("SDN") — U.S. Treasury.
- **UK OFSI Consolidated List of Financial Sanctions Targets**.

The methodology for screening against these lists is documented in:

- **FATF Recommendation 6** — "Targeted financial sanctions related to
  terrorism and terrorist financing".
- **FATF Recommendation 7** — "Targeted financial sanctions related to
  proliferation".
- **Wolfsberg Group "Sanctions Screening Guidance" (2019)** — covers
  fuzzy matching, transliteration, name-component rotation, score
  thresholds, and the difference between a hit and a true match.

### Customer-due-diligence framing

**FATF Recommendation 10** ("Customer Due Diligence") and the
**Association of Certified Fraud Examiners (ACFE) Fraud Examiners
Manual** (Investigation > KYC / CDD chapters) frame PEP / sanctions
screening as one component of a broader CDD process that also covers
identity verification, source-of-funds, source-of-wealth, ownership
mapping, and ongoing monitoring. This skill addresses only the PEP /
sanctions component; ownership mapping is handled by
`find-shell-companies`, money-flow tracing by `find-money-flow`.

## When this skill should fire

The resolver regex is intentionally broad. It fires when a brief
mentions any of:

- explicit screening vocabulary — `PEP`, `sanctions`, `screening`,
  `KYC`, `CDD`, `EDD`, `due diligence`, `adverse media`, `watchlist`,
  `OpenSanctions`, `Wolfsberg`, `FATF`;
- entity-role vocabulary — `beneficial owner`, `UBO`, `director`,
  `officer`, `shareholder`, `counterparty`, `client`, `individual`,
  `natural person`, `legal person`, `company`, `corporation`, `entity`.

The breadth is by design: in v2 the skill is a placeholder, so a missed
flag is more costly than a redundant one. In v3, when the lookup is
real, the resolver will likely be tightened.

## Skill behavior — step by step

For every brief routed to this skill, the agent harness does the
following. (The harness is implemented in `src/agent/`; this skill
itself is markdown-only methodology.)

1. **Identify candidate entities.**
   Walk the investigation corpus snapshot and collect every distinct
   mention of a natural person or legal person. Use the Aleph entity
   index where available (Aleph schema `Person`, `Company`,
   `Organization`, `LegalEntity`). For each mention, retain the source
   document id, page, and character offsets.

2. **Deduplicate by canonical name.**
   Group mentions by NFC-normalized name. Different spellings of the
   same entity (e.g. "ACME Corp." vs "Acme Corporation") are kept
   separate at this stage — disambiguation is downstream work and is
   not the responsibility of this skill.

3. **Emit one Note per distinct entity mention group.**
   - `claim`: `Entity "<name>" requires PEP / sanctions screening.`
   - `exact_quotes`: at least one `Quote` for that entity. The quote is
     the verbatim source-language text of the mention, with full
     provenance: `doc_id`, `page`, `char_offset_start`,
     `char_offset_end`, `extractor_version`,
     `normalized_text_sha256`, `source_lang`, and (if non-English)
     `quote_text_en` plus `translator_of_record`.
   - `confidence`: a v2 placeholder Note expresses the *flag*, not the
     screening result. Set `confidence` to a low-to-mid prior (0.3–0.5)
     reflecting the prior probability that an arbitrary named entity is
     PEP- or sanctions-relevant. v3 will overwrite this with the
     calibrated result of the actual lookup.
   - `why_relevant`: one sentence linking the entity to the brief —
     e.g. "Named as the contracting party in tender 2021/044, the
     subject of the investigation."
   - `tier`: `"investigation"` (the only tier supported in v2).
   - `skill_id`: `cross-reference-pep@v1`.

4. **Multilingual handling.**
   If the source language is not English:
   - populate `source_lang` with the ISO-639-1 code;
   - call the translator and put the English rendering in
     `quote_text_en`;
   - record the translator identifier (model + version) in
     `translator_of_record`;
   - **on translation failure**, leave `quote_text_en` as `None` and
     set `translator_of_record` to `<translator-id>:translation_failed`
     (exact suffix, non-empty prefix). Failure is logged, not silent.

5. **Substring verification.**
   Before the Note leaves the skill, the substring quote verifier must
   confirm that `quote_text` actually appears at the cited offsets in
   the cited document at the cited extractor version. Verifier failure
   triggers up to 3 retries (regenerate the quote with a different
   offset window); after the third failure, the Note is dropped and
   the drop is logged with reason. (CLAUDE.md rule 5.)

## What this skill explicitly does NOT do (v2)

- **No live PEP lookup.** No HTTP call to OpenSanctions, Dow Jones,
  WorldCheck, etc. v3 work.
- **No sanctions-list match.** v3 work.
- **No risk scoring.** A flag is not a score.
- **No entity disambiguation.** "John Smith" appearing in two documents
  produces two flags (or one flag with two quotes if the names are
  byte-equal after NFC normalization). Disambiguation is downstream.
- **No mandate-tier output.** v2 ships investigation-tier Notes only;
  mandate-tier behavior is v3 (CLAUDE.md premise 7).

## Output examples

### Example 1 — English brief, English document

Brief: *"Verify counterparty Acme Corp before approving the contract."*

Note (one of possibly several, abbreviated):

```
claim:        Entity "Acme Corp" requires PEP / sanctions screening.
exact_quotes: [{
  quote_text:                "Acme Corp",
  quote_text_en:             null,
  doc_id:                    "doc_42",
  page:                      1,
  char_offset_start:         128,
  char_offset_end:           137,
  extractor_version:         "tesseract-5.3.1@aleph-3.18",
  normalized_text_sha256:    "<sha256 of NFC-normalized doc text>",
  source_lang:               "en",
  translator_of_record:      null,
}]
confidence:   0.4
why_relevant: Named as the counterparty in the contract under review.
tier:         investigation
skill_id:     cross-reference-pep@v1
```

### Example 2 — Italian brief, Italian document

Brief: *"Verificare la controparte Società Beta S.r.l."*

Note:

```
claim:        Entity "Società Beta S.r.l." requires PEP / sanctions screening.
exact_quotes: [{
  quote_text:                "Società Beta S.r.l.",
  quote_text_en:             "Beta Company Ltd.",
  doc_id:                    "doc_77",
  page:                      2,
  char_offset_start:         44,
  char_offset_end:           63,
  extractor_version:         "tesseract-5.3.1@aleph-3.18",
  normalized_text_sha256:    "<sha256 of NFC-normalized doc text>",
  source_lang:               "it",
  translator_of_record:      "gemma-4-27b@2026-04-01",
}]
confidence:   0.4
why_relevant: Named as the counterparty in the investigation brief.
```

### Example 3 — Translation failure

Same as Example 2, but the translator was unavailable:

```
exact_quotes: [{
  ...
  source_lang:          "it",
  quote_text_en:        null,
  translator_of_record: "gemma-4-27b@2026-04-01:translation_failed",
}]
```

The quote is preserved in source language; the failure is logged.

## References

- FATF, *International Standards on Combating Money Laundering and the
  Financing of Terrorism & Proliferation* (FATF Recommendations) —
  Recommendations 6, 7, 10, 12 and Interpretive Notes.
  <https://www.fatf-gafi.org/en/topics/fatf-recommendations.html>
- Wolfsberg Group, *Wolfsberg Guidance on Politically Exposed Persons*,
  2017.
- Wolfsberg Group, *Wolfsberg Guidance on Sanctions Screening*, 2019.
- Association of Certified Fraud Examiners, *Fraud Examiners Manual* —
  Investigation section, KYC / CDD chapters.
- United Nations Security Council Consolidated List.
- EU Consolidated Financial Sanctions List (CFSP).
- U.S. Department of the Treasury, OFAC SDN List.
- UK OFSI Consolidated List of Financial Sanctions Targets.
- OpenSanctions project (planned v3 lookup target),
  <https://www.opensanctions.org>.
