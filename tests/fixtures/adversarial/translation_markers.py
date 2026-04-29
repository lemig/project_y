"""Forged translation-failure marker fixtures.

The Quote schema (`src/schema/note.py`) recognises a single, exact
translator-of-record suffix as a translation-failure marker:

    "<translator-id>:translation_failed"

with a NON-BLANK <translator-id>. Anything else MUST be rejected — partly
because we need a hard gate against silent loss in the audit log
(CLAUDE.md rule #5), and partly because a sloppy substring check would let
an attacker forge "this translation failed" markers to suppress translations
they don't want surfaced.

This module contains:
- the attack strings the schema currently rejects (`INVALID_FAILURE_MARKERS`)
- the legitimate markers the schema must accept (`VALID_FAILURE_MARKERS`)
- the legitimate non-failure translator IDs (`NON_FAILURE_TRANSLATORS`)
- the attack strings that exploit current-schema gaps and SHOULD be rejected
  but aren't yet (`KNOWN_SCHEMA_GAPS`)

The four attack patterns called out in the task spec
(`model:translation_failed-but-not-really`, `:translation_failed`,
` :translation_failed`, `model:translation_failed\\x00junk`) are all in
`INVALID_FAILURE_MARKERS`.

Consumed by: schema invariant tests (extending `tests/test_note_schema.py`).

The lists were verified against the current schema at fixture-build time:
every entry in `INVALID_FAILURE_MARKERS`, `VALID_FAILURE_MARKERS`, and
`NON_FAILURE_TRANSLATORS` was confirmed to behave as labelled. Every entry
in `KNOWN_SCHEMA_GAPS` is currently ACCEPTED by the schema and represents a
hardening opportunity; tests that consume that list should be marked
`xfail` until the schema rules are tightened.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Attack strings that the CURRENT schema correctly rejects.
# Each entry: (attack_string, why_it_must_be_rejected).
# ---------------------------------------------------------------------------
INVALID_FAILURE_MARKERS: list[tuple[str, str]] = [
    (
        "model:translation_failed-but-not-really",
        "substring forgery — extra chars after the suffix; suffix is not at end",
    ),
    (
        ":translation_failed",
        "empty translator-id prefix",
    ),
    (
        " :translation_failed",
        "whitespace-only translator-id prefix",
    ),
    (
        "\t:translation_failed",
        "tab-only translator-id prefix",
    ),
    (
        "  :translation_failed",
        "multiple-space translator-id prefix",
    ),
    (
        "argos-1.9:translation_failed\x00junk",
        "NUL byte plus junk after the marker — null-byte truncation forgery",
    ),
    (
        "argos-1.9:translation_failed ",
        "trailing space — suffix is not at end",
    ),
    (
        "argos-1.9:translation_failed\n",
        "trailing newline — suffix is not at end",
    ),
    (
        "argos-1.9:Translation_Failed",
        "wrong case — suffix is case-sensitive",
    ),
    (
        "argos-1.9:translation_FAILED",
        "wrong case (upper) — suffix is case-sensitive",
    ),
    (
        "argos-1.9: translation_failed",
        "space inside the suffix — separator should be ':' not ': '",
    ),
    (
        "argos-1.9_translation_failed",
        "underscore instead of colon separator",
    ),
    (
        "translation_failed",
        "no colon at all — bare suffix",
    ),
    (
        "argos-1.9:translation_failed:",
        "trailing colon after the suffix",
    ),
    (
        "argos-1.9:translation_failed#",
        "trailing hash — suffix is not at end",
    ),
]


# ---------------------------------------------------------------------------
# Attack strings that the CURRENT schema accepts but logically should reject.
# These exploit the substring-suffix-only check + .strip() prefix-emptiness
# logic. Tests should mark consuming cases `xfail(strict=True)` until the
# schema is tightened; flipping them to passing assertions is the regression
# signal that the gap closed.
# ---------------------------------------------------------------------------
KNOWN_SCHEMA_GAPS: list[tuple[str, str]] = [
    (
        "argos-1.9::translation_failed",
        "double colon: prefix is 'argos-1.9:' which is non-empty after .strip(), "
        "so the schema treats this as a valid marker even though the structural "
        "form is malformed (translator-id must not end in ':').",
    ),
    (
        "argos-1.9: :translation_failed",
        "trailing space + empty-prefix attack: prefix is 'argos-1.9: ' which "
        ".strip() reduces to 'argos-1.9:' (non-empty), so the schema accepts. "
        "Same root cause as the double-colon case — colon should be reserved "
        "as the marker separator.",
    ),
]


# ---------------------------------------------------------------------------
# Legitimate markers: must be accepted as `translator_of_record` for a non-EN
# quote with `quote_text_en=None`.
# ---------------------------------------------------------------------------
VALID_FAILURE_MARKERS: list[str] = [
    "argos-1.9:translation_failed",
    "deepl-2024-01:translation_failed",
    "gemma-4-27b@vllm-0.5.3:translation_failed",
    "google-translate-api-v3:translation_failed",
    "marian-mt-it-en@hf-2024-09:translation_failed",
    "x:translation_failed",  # one-character translator-id, still non-blank
]


# ---------------------------------------------------------------------------
# Legitimate non-failure translator IDs: must be accepted as
# `translator_of_record` for a non-EN quote with a non-empty `quote_text_en`.
# ---------------------------------------------------------------------------
NON_FAILURE_TRANSLATORS: list[str] = [
    "argos-1.9",
    "deepl-2024-01",
    "gemma-4-27b@vllm-0.5.3",
    "marian-mt-it-en@hf-2024-09",
    "human:miguel.cabero@olaf",
]


__all__ = [
    "INVALID_FAILURE_MARKERS",
    "KNOWN_SCHEMA_GAPS",
    "VALID_FAILURE_MARKERS",
    "NON_FAILURE_TRANSLATORS",
]
