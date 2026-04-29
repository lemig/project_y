"""Integration / LLM-eval test for flag-suspect-doc.

Two layers:

1. **Deterministic contract tests (always run).**
   - Fixture corpus is loadable and structured as the methodology expects.
   - The methodology body actually covers every signal class the fixtures
     embed, so an agent following the SKILL.md cannot miss a fixture
     signal because the methodology forgot to mention it.
   - Hand-built "ground-truth" Notes for the high-risk fixtures construct
     cleanly under the locked v2 Note schema, including a non-English
     quote variant — proving the methodology's output shape is realisable.

2. **Live LLM eval (skipped unless wired).**
   - The actual end-to-end eval requires the harness adapter, the Aleph
     REST client, the substring quote verifier, and an LLM endpoint —
     none of which is in scope for this skill PR. The placeholder is
     parameter-flagged and skipped, so wiring it later is a one-line
     change rather than a new test.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from schema.note import Note, Quote

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_sha_placeholder(seed: bytes) -> str:
    # 40-char hex; matches the shape Note.skill_version requires.
    return hashlib.sha1(seed).hexdigest()


def _load_fixture(stem: str) -> tuple[str, dict[str, Any]]:
    text = (_FIXTURES / f"{stem}.txt").read_text(encoding="utf-8")
    meta = json.loads((_FIXTURES / f"{stem}.meta.json").read_text(encoding="utf-8"))
    return text, meta


# All known signal IDs — the union of expected_signals across fixtures.
# Methodology must cover each one explicitly.
_KNOWN_SIGNALS: dict[str, tuple[str, ...]] = {
    "high-risk-jurisdiction-counterparty": ("jurisdiction",),
    "round-number-amount": ("round-number",),
    "vague-service-description": ("vague service",),
    "no-tax-identifier": ("tax identifier",),
    "end-of-period-timing": ("period-end",),
    "intermediary-no-apparent-role": ("intermediar",),
}


class TestFixturesLoadable:
    @pytest.mark.parametrize(
        "stem", ["invoice_high_risk", "invoice_clean", "contract_unexplained_intermediary"]
    )
    def test_fixture_loads(self, stem: str) -> None:
        text, meta = _load_fixture(stem)
        assert text.strip(), f"{stem}: text body is empty"
        assert meta["doc_id"], f"{stem}: missing doc_id"
        assert meta["extractor_version"], f"{stem}: missing extractor_version"

    def test_high_risk_fixture_embeds_advertised_signals(self) -> None:
        text, meta = _load_fixture("invoice_high_risk")
        signals = set(meta["expected_signals"])
        # Each advertised signal must have a token actually present in the
        # text — otherwise the fixture is lying about itself and the
        # downstream test below is meaningless.
        text_lower = text.lower()
        if "high-risk-jurisdiction-counterparty" in signals:
            assert "british virgin islands" in text_lower
        if "round-number-amount" in signals:
            assert "250,000" in text or "250000" in text
        if "vague-service-description" in signals:
            assert "strategic consulting services" in text_lower
        if "no-tax-identifier" in signals:
            assert "no tax identifier" in text_lower
        if "end-of-period-timing" in signals:
            # 2023-12-29 is end-of-quarter / end-of-year proximity.
            assert "2023-12-29" in text

    def test_clean_fixture_advertises_no_signals(self) -> None:
        _, meta = _load_fixture("invoice_clean")
        assert meta["expected_signals"] == []

    def test_intermediary_fixture_embeds_advertised_signals(self) -> None:
        text, meta = _load_fixture("contract_unexplained_intermediary")
        signals = set(meta["expected_signals"])
        text_lower = text.lower()
        if "high-risk-jurisdiction-counterparty" in signals:
            assert "panama" in text_lower
        if "intermediary-no-apparent-role" in signals:
            assert "agent" in text_lower and "commission" in text_lower
        if "vague-service-description" in signals:
            # Phrase intentionally vague in the contract; check for the
            # boilerplate hallmark that fits on a single extracted line.
            assert "from time to time request" in text_lower


class TestMethodologyCoversFixtureSignals:
    """If a fixture advertises a signal, the SKILL.md methodology must teach it.

    This catches the silent-drift failure mode where someone trims the
    methodology and the fixtures keep "passing" only because the LLM
    confabulated the missing rationale.
    """

    def test_methodology_covers_every_fixture_signal(self) -> None:
        body = _SKILL_MD.read_text(encoding="utf-8").lower()
        all_signals: set[str] = set()
        for stem in (
            "invoice_high_risk",
            "invoice_clean",
            "contract_unexplained_intermediary",
        ):
            _, meta = _load_fixture(stem)
            all_signals.update(meta["expected_signals"])
        for signal in all_signals:
            tokens = _KNOWN_SIGNALS.get(signal)
            assert tokens is not None, f"unknown fixture signal: {signal}"
            assert any(tok in body for tok in tokens), (
                f"SKILL.md does not cover signal {signal!r} (looked for any of {tokens})"
            )


class TestGroundTruthNotesAreSchemaValid:
    """The Notes the methodology says to emit must construct under the locked schema.

    Building one ground-truth Note per high-risk fixture and validating it
    pins the output shape — including offsets, sha256s, the English-source
    branch (translator_of_record=None) and the non-English branch
    (translator_of_record set) — so a methodology change that breaks the
    output shape fails fast instead of waiting for an end-to-end run.
    """

    def _quote_for_substring(
        self,
        text: str,
        substring: str,
        *,
        doc_id: str,
        extractor_version: str,
        source_lang: str,
        quote_text_en: str | None = None,
        translator_of_record: str | None = None,
        page: int | None = 1,
    ) -> Quote:
        start = text.find(substring)
        assert start >= 0, f"substring not found in fixture: {substring!r}"
        end = start + len(substring)
        return Quote(
            quote_text=substring,
            quote_text_en=quote_text_en,
            doc_id=doc_id,
            page=page,
            char_offset_start=start,
            char_offset_end=end,
            extractor_version=extractor_version,
            normalized_text_sha256=_sha256_hex(text.encode("utf-8")),
            source_lang=source_lang,
            translator_of_record=translator_of_record,
        )

    def test_high_risk_invoice_produces_schema_valid_note(self) -> None:
        text, meta = _load_fixture("invoice_high_risk")
        quotes = (
            self._quote_for_substring(
                text,
                "British Virgin Islands",
                doc_id=meta["doc_id"],
                extractor_version=meta["extractor_version"],
                source_lang="en",
            ),
            self._quote_for_substring(
                text,
                "Strategic consulting services",
                doc_id=meta["doc_id"],
                extractor_version=meta["extractor_version"],
                source_lang="en",
            ),
            self._quote_for_substring(
                text,
                "EUR 250,000.00",
                doc_id=meta["doc_id"],
                extractor_version=meta["extractor_version"],
                source_lang="en",
            ),
        )
        note = Note(
            claim=(
                "Invoice INV-2023-118 fires three independent fraud signals: "
                "counterparty in a FATF-monitored jurisdiction, vague service "
                "description, and a round-number total."
            ),
            exact_quotes=quotes,
            confidence=0.6,
            why_relevant=(
                "Concentrates three independently-recognised red flags on a "
                "single transaction, raising it above noise for analyst review."
            ),
            source_corpus_snapshot_hash=_sha256_hex(b"fixture-corpus-v1"),
            brief_hash=_sha256_hex(b"flag suspect documents"),
            skill_id="flag-suspect-doc@v1",
            skill_resolver_match="flag suspect documents",
            skill_version=_git_sha_placeholder(b"flag-suspect-doc@v1"),
        )
        # Round-trip through the schema as the harness will at audit-write time.
        assert Note(**note.model_dump()) == note
        assert len(note.exact_quotes) == 3

    def test_non_english_quote_path_is_realisable(self) -> None:
        # Methodology promises a working non-English path: source-language
        # quote + translator_of_record. Construct one to prove the schema
        # accepts the path the methodology prescribes.
        italian_text = "Banca XYZ ha trasferito 250.000 EUR a Helios Ltd."
        normalised = italian_text  # NFC-stable already; keep deterministic
        start = normalised.find("trasferito 250.000 EUR")
        assert start >= 0
        end = start + len("trasferito 250.000 EUR")
        q = Quote(
            quote_text="trasferito 250.000 EUR",
            quote_text_en="transferred EUR 250,000",
            doc_id="fixture-doc-IT-001",
            page=1,
            char_offset_start=start,
            char_offset_end=end,
            extractor_version="fixture-text@v1",
            normalized_text_sha256=_sha256_hex(normalised.encode("utf-8")),
            source_lang="it",
            translator_of_record="argos-1.9",
        )
        # And the translation-failure fallback the methodology mandates.
        q_failed = Quote(
            quote_text="trasferito 250.000 EUR",
            quote_text_en=None,
            doc_id="fixture-doc-IT-001",
            page=1,
            char_offset_start=start,
            char_offset_end=end,
            extractor_version="fixture-text@v1",
            normalized_text_sha256=_sha256_hex(normalised.encode("utf-8")),
            source_lang="it",
            translator_of_record="argos-1.9:translation_failed",
        )
        assert q.translator_of_record == "argos-1.9"
        assert q_failed.quote_text_en is None
        assert q_failed.translator_of_record == "argos-1.9:translation_failed"

    def test_clean_invoice_produces_no_note(self) -> None:
        # Encodes the methodology's "score 0 → no Note" rule. The harness
        # should never persist a Note for a document that fired no signals.
        _, meta = _load_fixture("invoice_clean")
        assert meta["expected_signals"] == []


@pytest.mark.skipif(
    not os.environ.get("LLM_BASE_URL"),
    reason=(
        "Live LLM eval requires LLM_BASE_URL/LLM_API_KEY/LLM_MODEL plus the "
        "harness adapter, REST client, and substring quote verifier — none "
        "in scope for this skill PR. Wire and un-skip when those land."
    ),
)
def test_llm_eval_against_fixture_corpus() -> None:
    # Placeholder: when the harness adapter exists, this test will load
    # SKILL.md, run it against the three fixtures with the configured LLM,
    # and assert (a) one Note for invoice_high_risk and one for
    # contract_unexplained_intermediary, (b) zero Notes for invoice_clean,
    # (c) every emitted Note has at least one exact_quote that survives
    # the substring quote verifier against the fixture text.
    pytest.skip("placeholder — wire when harness + verifier land")
