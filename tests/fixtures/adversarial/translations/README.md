# Adversarial fixtures — fluent-bad translations

## What this tests

The `fluent-bad-translation` hard-gated bug-class test (CLAUDE.md). The
threat model: an LLM translator produces grammatical, plausible-sounding
English that has the wrong semantics — wrong amount, inverted polarity,
false-friend cognate, literal rendering of a fixed expression, flipped modal.
Generic fluency / round-trip checks miss these because the bad output reads as
natural English. The gate must catch them.

## Format

`cases.json` — schema version `v2-adversarial-fluent-bad-translations-2026-04-29`.

Each entry under `cases[]`:

| field | meaning |
|---|---|
| `id` | stable handle (test parameter id) |
| `source_lang` | ISO-639-1 of the source quote (`it`, `ro`, `fr`, `de`, or `es`) |
| `source_quote` | the verbatim non-EN source text |
| `fluent_bad_en` | a grammatically perfect English translation that is semantically wrong |
| `fluent_correct_en` | a correct English translation |
| `what_went_wrong` | one-paragraph description of the failure mode |
| `harm_class` | one of: `amount_understatement`, `polarity_inversion`, `false_friend`, `fixed_expression_literalism`, `modal_inversion`, `temporal_drift` |

## Coverage (15 cases — 3 per language × 5 languages)

| harm_class | count | what it looks like |
|---|---|---|
| `amount_understatement` | 5 | thousands/decimal separator inversion → 3–6 orders of magnitude off |
| `polarity_inversion` | 4 | dropped `non` / `nu` / `refusé` / `no` |
| `fixed_expression_literalism` | 3 | shell-company term ('société écran', 'Briefkastenfirma', 'empresa fantasma') rendered literally |
| `false_friend` | 1 | RO 'actualmente' → EN 'actually' (means 'currently') |
| `modal_inversion` | 1 | DE 'darf erst nach' (may only after) → 'must before' |
| `temporal_drift` | 1 | preserved-numeric-date dd/mm read as mm/dd |

Each language gets a roughly representative slice of the harm classes; full
coverage of every (lang × harm-class) cell would be a longer-running
integration corpus. The 15 here are the minimum gate.

## What the gate should do

The fluent-bad-translation gate is one of the six in CLAUDE.md. It is NOT a
generic fluency check; per CLAUDE.md determinism rules, no LLM sits in the
trust path. Acceptable implementations include:

- targeted regex/numeric-parse checks over money + date strings (catches
  `amount_understatement`, `temporal_drift`)
- bilingual negation-particle audit (catches `polarity_inversion`)
- a maintained whitelist/blocklist for fraud-typology fixed expressions
  (catches `fixed_expression_literalism` and the `actualmente` false friend)
- targeted modal-verb assertion in DE (catches `modal_inversion`)

What the gate must NOT do: ask an LLM "is this translation correct?" — that
re-introduces a non-deterministic component into the trust path.

## Source

Hand-crafted, fully synthetic. Source quotes are short flavored sentences
modelled on common OLAF case-doc phrasings (bank transfers, contracts,
ministerial decisions, liquidations). No real entities. The harm classes
themselves are drawn from observed translation failures in OLAF and partner
agencies' multilingual case work — generalised here without referencing any
specific case.
