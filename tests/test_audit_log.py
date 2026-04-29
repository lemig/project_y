"""Audit-log writer tests.

Pin the no-silent-loss contract: every drop logs a reason, every translation
failure carries the canonical ``:translation_failed`` suffix, every entry is
appended (never overwritten) with a UTC timestamp.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from audit.log import (
    AuditLog,
    AuditLogError,
    InvalidInvestigationId,
    ObservationStatus,
)
from schema.note import Note, Quote


def _sha(seed: bytes = b"x") -> str:
    return hashlib.sha256(seed).hexdigest()


def _git_sha(seed: bytes = b"skill") -> str:
    return hashlib.sha1(seed).hexdigest()


def _quote(**overrides: Any) -> Quote:
    base: dict[str, Any] = dict(
        quote_text="Banca Intesa transferred 120,000 EUR",
        quote_text_en=None,
        doc_id="doc-42",
        page=3,
        char_offset_start=128,
        char_offset_end=164,
        extractor_version="tesseract-5.3.1@aleph-3.18",
        normalized_text_sha256=_sha(),
        source_lang="en",
        translator_of_record=None,
    )
    base.update(overrides)
    return Quote(**base)


def _note(**overrides: Any) -> Note:
    base: dict[str, Any] = dict(
        claim="120k flowed from A to B on 2024-03-12",
        exact_quotes=(_quote(),),
        confidence=0.85,
        why_relevant="Establishes the contested transfer.",
        source_corpus_snapshot_hash=_sha(b"corpus"),
        brief_hash=_sha(b"brief"),
        skill_id="find-money-flow@v1",
        skill_resolver_match="money flow",
        skill_version=_git_sha(),
    )
    base.update(overrides)
    return Note(**base)


def _read_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


class TestConstruction:
    def test_creates_directory_lazily(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "audit"
        log = AuditLog("inv-001", base_dir=target)
        assert target.exists()
        assert log.path == target / "inv-001.jsonl"

    def test_rejects_unsafe_investigation_id(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidInvestigationId):
            AuditLog("../escape", base_dir=tmp_path)
        with pytest.raises(InvalidInvestigationId):
            AuditLog("with/slash", base_dir=tmp_path)
        with pytest.raises(InvalidInvestigationId):
            AuditLog("", base_dir=tmp_path)
        with pytest.raises(InvalidInvestigationId):
            AuditLog("-leading-dash", base_dir=tmp_path)
        with pytest.raises(InvalidInvestigationId):
            AuditLog("with space", base_dir=tmp_path)

    def test_accepts_safe_investigation_ids(self, tmp_path: Path) -> None:
        AuditLog("inv-001", base_dir=tmp_path)
        AuditLog("INV_001", base_dir=tmp_path)
        AuditLog("a", base_dir=tmp_path)
        AuditLog("A1B2C3", base_dir=tmp_path)


class TestObservation:
    def test_pass_observation_no_reason(self, tmp_path: Path) -> None:
        log = AuditLog("inv-001", base_dir=tmp_path)
        log.log_observation(_note(), ObservationStatus.PASS)

        entries = _read_lines(log.path)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["kind"] == "observation"
        assert entry["payload"]["status"] == "pass"
        assert entry["payload"]["reason"] is None
        assert entry["payload"]["note"]["claim"] == "120k flowed from A to B on 2024-03-12"
        assert entry["investigation_id"] == "inv-001"
        assert "ts" in entry

    def test_non_pass_observation_requires_reason(self, tmp_path: Path) -> None:
        log = AuditLog("inv-001", base_dir=tmp_path)
        with pytest.raises(AuditLogError):
            log.log_observation(_note(), ObservationStatus.FAIL_QUOTE_MISMATCH)

    def test_non_pass_observation_with_reason_persists(self, tmp_path: Path) -> None:
        log = AuditLog("inv-001", base_dir=tmp_path)
        log.log_observation(
            _note(),
            ObservationStatus.FAIL_QUOTE_MISMATCH,
            reason="offsets drifted after re-extraction",
        )
        entries = _read_lines(log.path)
        assert entries[0]["payload"]["status"] == "fail_quote_mismatch"
        assert entries[0]["payload"]["reason"] == "offsets drifted after re-extraction"


class TestDrop:
    def test_drop_records_reason_and_context(self, tmp_path: Path) -> None:
        log = AuditLog("inv-001", base_dir=tmp_path)
        log.log_drop(
            "verifier exhausted retries",
            context={"skill_id": "find-money-flow@v1", "attempts": 3},
        )
        entries = _read_lines(log.path)
        assert entries[0]["kind"] == "drop"
        assert entries[0]["payload"]["reason"] == "verifier exhausted retries"
        assert entries[0]["payload"]["context"] == {
            "skill_id": "find-money-flow@v1",
            "attempts": 3,
        }

    def test_drop_requires_non_empty_reason(self, tmp_path: Path) -> None:
        log = AuditLog("inv-001", base_dir=tmp_path)
        with pytest.raises(AuditLogError):
            log.log_drop("", context={})
        with pytest.raises(AuditLogError):
            log.log_drop("   ", context={})


class TestTranslationFailure:
    def test_appends_canonical_suffix(self, tmp_path: Path) -> None:
        log = AuditLog("inv-001", base_dir=tmp_path)
        q = _quote(
            source_lang="it",
            quote_text="Banca Intesa ha trasferito 120.000 EUR",
            quote_text_en=None,
            translator_of_record="argos-1.9:translation_failed",
        )
        log.log_translation_failure(
            AuditLog.quote_meta(q),
            translator="argos-1.9",
            error="Connection refused",
        )
        entries = _read_lines(log.path)
        assert entries[0]["kind"] == "translation_failure"
        assert entries[0]["payload"]["translator_of_record"] == "argos-1.9:translation_failed"
        assert entries[0]["payload"]["error"] == "Connection refused"
        assert entries[0]["payload"]["quote_meta"]["doc_id"] == "doc-42"
        assert entries[0]["payload"]["quote_meta"]["source_lang"] == "it"
        # quote_text_en MUST not leak into the audit log when translation failed.
        assert "quote_text_en" not in entries[0]["payload"]["quote_meta"]

    def test_rejects_pre_suffixed_translator(self, tmp_path: Path) -> None:
        log = AuditLog("inv-001", base_dir=tmp_path)
        with pytest.raises(AuditLogError):
            log.log_translation_failure(
                {"doc_id": "x"},
                translator="argos-1.9:translation_failed",
                error="boom",
            )

    def test_requires_translator_id(self, tmp_path: Path) -> None:
        log = AuditLog("inv-001", base_dir=tmp_path)
        with pytest.raises(AuditLogError):
            log.log_translation_failure({}, translator="", error="boom")
        with pytest.raises(AuditLogError):
            log.log_translation_failure({}, translator="   ", error="boom")

    def test_requires_error_description(self, tmp_path: Path) -> None:
        log = AuditLog("inv-001", base_dir=tmp_path)
        with pytest.raises(AuditLogError):
            log.log_translation_failure({}, translator="argos-1.9", error="")


class TestAppendOnly:
    def test_writes_one_line_per_call_and_appends(self, tmp_path: Path) -> None:
        log = AuditLog("inv-001", base_dir=tmp_path)
        log.log_observation(_note(), ObservationStatus.PASS)
        log.log_drop("dropped after retries", context={"attempts": 3})
        log.log_translation_failure(
            {"doc_id": "doc-42"}, translator="argos-1.9", error="boom"
        )

        raw = log.path.read_text("utf-8")
        # Exactly three '\n' terminators, one per entry, no truncation.
        assert raw.count("\n") == 3
        kinds = [json.loads(line)["kind"] for line in raw.splitlines()]
        assert kinds == ["observation", "drop", "translation_failure"]

    def test_reopen_appends_rather_than_overwriting(self, tmp_path: Path) -> None:
        log1 = AuditLog("inv-001", base_dir=tmp_path)
        log1.log_drop("first", context={})

        # Brand-new instance, same investigation: must extend the existing file.
        log2 = AuditLog("inv-001", base_dir=tmp_path)
        log2.log_drop("second", context={})

        entries = _read_lines(log1.path)
        assert [e["payload"]["reason"] for e in entries] == ["first", "second"]

    def test_jsonl_lines_are_independently_parseable(self, tmp_path: Path) -> None:
        log = AuditLog("inv-001", base_dir=tmp_path)
        for i in range(5):
            log.log_drop(f"reason {i}", context={"i": i})
        for line in log.path.read_text("utf-8").splitlines():
            json.loads(line)  # raises if any line is malformed


class TestEncoding:
    def test_unicode_payload_persists_correctly(self, tmp_path: Path) -> None:
        log = AuditLog("inv-001", base_dir=tmp_path)
        log.log_drop(
            "café receipt orphaned",
            context={"city": "Bruxelles", "note": "à confirmer"},
        )
        entries = _read_lines(log.path)
        assert entries[0]["payload"]["reason"] == "café receipt orphaned"
        assert entries[0]["payload"]["context"]["note"] == "à confirmer"
