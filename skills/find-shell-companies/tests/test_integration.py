"""Integration test for find-shell-companies.

Two layers, both of which must pass before the skill can ship:

A. **Deterministic shape gate (default-run)**: load the skill via the
   `DeepAgentsHarness.load_skill` path, and verify that the skill's
   contracted output (one `Note` per scored entity, with quotes per fired
   indicator) round-trips through `schema.note.Note` AND the substring
   quote verifier against an in-memory fixture corpus. This is a
   "shape & wiring" test — does not call an LLM. Fails fast if the
   contract drifts.

B. **Live LLM eval (`-m integration`)**: when `LLM_BASE_URL`,
   `LLM_API_KEY`, and `LLM_MODEL` are set, drive `planner_run` with a
   brief whose text matches the skill's resolver, and assert the planner
   run completes (non-empty `plan_log`, brief hash recorded).
   The full Notes-emission path is not yet wired in v2 (per
   `DeepAgentsHarness.spawn_subagent`'s `NotImplementedError`); when it
   lands, this test will be extended to assert Notes shape end-to-end.

The fixture corpus uses synthetic text — no real-case bytes — so the
test is safe to commit to the public-facing repo.
"""

from __future__ import annotations

import hashlib
import os
import unicodedata
from pathlib import Path

import pytest

from agent.deep_agents_harness import DeepAgentsHarness
from schema.brief import Brief
from schema.note import Note, Quote
from verifier.document_source import (
    DocumentNotFound,
    DocumentSource,
    PageNotFound,
)
from verifier.substring import VerificationResult, verify_quote

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SKILLS_ROOT = _REPO_ROOT / "skills"

# Realistic SHA-1 / SHA-256 placeholders for harness-supplied fields.
_GOOD_SHA256 = "a" * 64
_GOOD_GIT_SHA = "b" * 40


# ---------------------------------------------------------------------------
# Fixture corpus — synthetic documents covering the 5 indicator patterns
# ---------------------------------------------------------------------------

DOC_REGISTRY_BVI = (
    "CERTIFICATE OF INCORPORATION\n"
    "BVI Business Companies Act, 2004\n"
    "Company Name: ACME Holdings Ltd\n"
    "Company Number: 2098431\n"
    "Date of Incorporation: 14 January 2024\n"
    "Registered Office: P.O. Box 957, Offshore Incorporations Centre, "
    "Road Town, Tortola, British Virgin Islands\n"
    "Registered Agent: Trident Trust Company (BVI) Limited\n"
)

DOC_CONTRACT_EU = (
    "PROCUREMENT CONTRACT — Reference EU-2024-CT-0481\n"
    "Awarding Authority: Directorate-General for Health (DG SANTE)\n"
    "Contractor: ACME Holdings Ltd, P.O. Box 957, Road Town, Tortola, "
    "British Virgin Islands\n"
    "Contract Value: 1,840,000 EUR\n"
    "Date of Award: 12 March 2024\n"
    "Subject: medical-equipment supply, Lot 3\n"
)

DOC_KYC_QUESTIONNAIRE = (
    "KYC QUESTIONNAIRE — ACME Holdings Ltd\n"
    "Section 4 — Beneficial Ownership\n"
    "Q4.1 Ultimate beneficial owner (natural person, ≥25% control): "
    "to be confirmed\n"
    "Q4.2 Direct shareholder: Pacific Trustees (Nevis) Inc.\n"
    "Q4.3 Director: John A. Smith — nominee director, "
    "appointed by registered agent\n"
)

DOC_REGISTRY_DUPLICATE = (
    "CERTIFICATE OF INCORPORATION\n"
    "Company Name: Beta Logistics Ltd\n"
    "Company Number: 2098445\n"
    "Date of Incorporation: 21 January 2024\n"
    "Registered Office: P.O. Box 957, Offshore Incorporations Centre, "
    "Road Town, Tortola, British Virgin Islands\n"
    "Registered Agent: Trident Trust Company (BVI) Limited\n"
)

# Italian-language registry document — exercises the multilingual path.
DOC_REGISTRY_IT = (
    "VISURA CAMERALE\n"
    "Denominazione: Gamma Servizi S.r.l.\n"
    "Sede legale: Via Roma 1, 00100 Roma, Italia\n"
    "Data di costituzione: 03 febbraio 2024\n"
    "Amministratore unico: Mario Rossi\n"
)


CORPUS: dict[str, str] = {
    "doc-registry-bvi-acme": DOC_REGISTRY_BVI,
    "doc-contract-eu-0481": DOC_CONTRACT_EU,
    "doc-kyc-acme": DOC_KYC_QUESTIONNAIRE,
    "doc-registry-bvi-beta": DOC_REGISTRY_DUPLICATE,
    "doc-registry-it-gamma": DOC_REGISTRY_IT,
}


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _sha256(text: str) -> str:
    return hashlib.sha256(_nfc(text).encode("utf-8")).hexdigest()


class _InMemorySource:
    """Implements `DocumentSource` Protocol against a `dict[doc_id, text]`."""

    def __init__(self, corpus: dict[str, str]) -> None:
        self._corpus = corpus

    def get_text(self, doc_id: str, page: int | None = None) -> str:
        if doc_id not in self._corpus:
            raise DocumentNotFound(doc_id)
        if page is not None and page != 1:
            raise PageNotFound(f"{doc_id} page {page}")
        return self._corpus[doc_id]


@pytest.fixture
def source() -> DocumentSource:
    return _InMemorySource(CORPUS)


# ---------------------------------------------------------------------------
# A. Deterministic shape gate
# ---------------------------------------------------------------------------


def test_skill_loads_through_harness(tmp_path: Path) -> None:
    """The harness's `load_skill` path is the planner's actual entry point.
    If our SKILL.md doesn't load through it, the planner can never invoke us.
    """
    h = DeepAgentsHarness(skills_root=_SKILLS_ROOT, checkpoints_dir=tmp_path)
    skill = h.load_skill("find-shell-companies@v1")
    assert skill.frontmatter.name == "find-shell-companies"
    assert skill.frontmatter.version == "v1"
    assert skill.skill_id == "find-shell-companies@v1"
    # 40-char hex SHA-1 (validated by `Skill` model on construction).
    assert len(skill.git_sha) == 40
    # Body must reference at least one indicator code so the planner has a
    # shot at producing structured output.
    for code in ("I1", "I2", "I3", "I4", "I5"):
        assert code in skill.body, f"skill body must reference indicator {code}"


def _quote_for(doc_id: str, text: str, snippet: str, *, source_lang: str = "en", quote_text_en: str | None = None, translator: str | None = None) -> Quote:
    doc = CORPUS[doc_id]
    start = doc.index(snippet)
    return Quote(
        quote_text=snippet,
        quote_text_en=quote_text_en,
        doc_id=doc_id,
        page=None,
        char_offset_start=start,
        char_offset_end=start + len(snippet),
        extractor_version="fixture-extractor-1.0",
        normalized_text_sha256=_sha256(doc),
        source_lang=source_lang,
        translator_of_record=translator,
    )


def test_acme_note_for_4of5_indicators_passes_verifier(source: DocumentSource) -> None:
    """ACME Holdings Ltd in the fixture fires I1 (BVI), I2 (incorporated
    Jan 2024 + contract awarded Mar 2024 → <12mo), I3 (shared registered
    address with Beta Logistics), and I5 (UBO 'to be confirmed'). Build the
    Note the skill is contracted to emit and round-trip every quote through
    the substring verifier — proves the skill output shape is achievable.
    """
    quotes = (
        # I1 — high-secrecy jurisdiction (BVI) on the registration cert.
        _quote_for(
            "doc-registry-bvi-acme",
            CORPUS["doc-registry-bvi-acme"],
            "Road Town, Tortola, British Virgin Islands",
        ),
        # I2a — incorporation date.
        _quote_for(
            "doc-registry-bvi-acme",
            CORPUS["doc-registry-bvi-acme"],
            "Date of Incorporation: 14 January 2024",
        ),
        # I2b — contract award date (≤12mo after incorporation).
        _quote_for(
            "doc-contract-eu-0481",
            CORPUS["doc-contract-eu-0481"],
            "Date of Award: 12 March 2024",
        ),
        # I3 — shared registered address (matches Beta Logistics doc below).
        _quote_for(
            "doc-registry-bvi-acme",
            CORPUS["doc-registry-bvi-acme"],
            "P.O. Box 957, Offshore Incorporations Centre",
        ),
        _quote_for(
            "doc-registry-bvi-beta",
            CORPUS["doc-registry-bvi-beta"],
            "P.O. Box 957, Offshore Incorporations Centre",
        ),
        # I5 — UBO field evasive.
        _quote_for(
            "doc-kyc-acme",
            CORPUS["doc-kyc-acme"],
            "Ultimate beneficial owner (natural person, ≥25% control): "
            "to be confirmed",
        ),
    )

    note = Note(
        claim="ACME Holdings Ltd scores 4/5 on shell-company indicators: I1, I2, I3, I5.",
        exact_quotes=quotes,
        confidence=0.80,  # 4/5 → 0.80 per skill body's deterministic mapping
        why_relevant=(
            "ACME Holdings is the contractor on EU-2024-CT-0481 (1.84M EUR). "
            "BVI registration, incorporation under 2 months before award, "
            "shared registered address with another corpus entity, and an "
            "evasive UBO field together match the FATF/StAR letterbox-company "
            "red-flag set."
        ),
        tier="investigation",
        source_corpus_snapshot_hash=_GOOD_SHA256,
        brief_hash=_GOOD_SHA256,
        skill_id="find-shell-companies@v1",
        skill_resolver_match="shell companies",
        skill_version=_GOOD_GIT_SHA,
    )

    # Round-trip every quote through the substring verifier. If any fail the
    # skill could not have emitted this Note (the verifier is the hard gate).
    for q in note.exact_quotes:
        result = verify_quote(q, source)
        assert result is VerificationResult.PASS, (
            f"quote failed verification ({result}): {q.quote_text!r} "
            f"in {q.doc_id}"
        )


def test_italian_note_quote_carries_translator_of_record(source: DocumentSource) -> None:
    """Multilingual contract per CLAUDE.md: source-language verbatim quote
    plus EN translation, with `translator_of_record` always set when the
    source is non-EN. The schema enforces this; we exercise the path here so
    the skill's contract (and the test fixtures) genuinely cover it.
    """
    snippet = "Data di costituzione: 03 febbraio 2024"
    doc = CORPUS["doc-registry-it-gamma"]
    start = doc.index(snippet)
    q = Quote(
        quote_text=snippet,
        quote_text_en="Date of incorporation: 3 February 2024",
        doc_id="doc-registry-it-gamma",
        page=None,
        char_offset_start=start,
        char_offset_end=start + len(snippet),
        extractor_version="fixture-extractor-1.0",
        normalized_text_sha256=_sha256(doc),
        source_lang="it",
        translator_of_record="opus-mt-it-en@2024.07",
    )
    assert verify_quote(q, source) is VerificationResult.PASS


def test_translation_failure_marker_is_acceptable(source: DocumentSource) -> None:
    """Per CLAUDE.md, on translation failure the skill must NOT silently drop
    the quote — it must keep the source-language verbatim with
    `translator_of_record="<id>:translation_failed"` and `quote_text_en=None`.
    The schema accepts this exact shape; the verifier still passes.
    """
    snippet = "Sede legale: Via Roma 1, 00100 Roma, Italia"
    doc = CORPUS["doc-registry-it-gamma"]
    start = doc.index(snippet)
    q = Quote(
        quote_text=snippet,
        quote_text_en=None,
        doc_id="doc-registry-it-gamma",
        page=None,
        char_offset_start=start,
        char_offset_end=start + len(snippet),
        extractor_version="fixture-extractor-1.0",
        normalized_text_sha256=_sha256(doc),
        source_lang="it",
        translator_of_record="opus-mt-it-en@2024.07:translation_failed",
    )
    assert verify_quote(q, source) is VerificationResult.PASS


# ---------------------------------------------------------------------------
# B. Live LLM eval — gated on env vars; skipped in default runs
# ---------------------------------------------------------------------------


_REQUIRED_ENV = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")


@pytest.mark.integration
@pytest.mark.skipif(
    not all(k in os.environ for k in _REQUIRED_ENV),
    reason=(
        "Set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL to run the live-endpoint "
        "find-shell-companies eval."
    ),
)
def test_planner_run_against_live_endpoint(tmp_path: Path) -> None:
    """Drives the harness with a brief whose text matches the
    `find-shell-companies` resolver. End-to-end Notes assertion is deferred
    until `spawn_subagent` skill execution lands (currently raises
    NotImplementedError per `DeepAgentsHarness.spawn_subagent`); for now we
    assert the planner round-trip succeeds and the brief hash is recorded.
    """
    h = DeepAgentsHarness(skills_root=_SKILLS_ROOT, checkpoints_dir=tmp_path)
    brief = Brief(
        text=(
            "Find shell companies in the corpus and report each one with "
            "score and quote evidence. Reply briefly."
        ),
        corpus_snapshot_hash=_GOOD_SHA256,
    )
    result = h.planner_run(brief)
    assert len(result.plan_log) >= 1
    assert h._state.last_brief_hash == brief.compute_hash()
