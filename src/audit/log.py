"""Append-only JSONL audit log — the third pure-Python trust component.

Per CLAUDE.md: "No silent loss in the audit log. Every dropped note logs the
reason. Every translation failure logs translator_of_record:
'<model>@<version>:translation_failed' and continues with quote_text_en: null."

This module provides the writer. It does NOT decide policy — it records
verification outcomes, drops, and translation failures with enough provenance
that a reviewer can reconstruct what was kept and what was discarded for any
investigation.

Append-only is enforced by convention (open in "a" mode, never truncate).
Files live at ``data/audit/<investigation_id>.jsonl``. Each line is a
self-contained JSON object with ``ts`` (UTC ISO-8601), ``kind``, and ``payload``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from schema.note import Note, Quote
from verifier.substring import VerificationResult

# VerificationResult covers the verifier's enum, but observations also need a
# DROPPED status for notes the harness throws away after retries are exhausted.
ObservationStatus = VerificationResult

DEFAULT_AUDIT_DIR = Path("data/audit")
TRANSLATION_FAILED_SUFFIX = ":translation_failed"
_INVESTIGATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,127}$")


class AuditLogError(Exception):
    """Base for audit-log errors."""


class InvalidInvestigationId(AuditLogError):
    """The investigation_id is unsafe as a filename."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _validate_investigation_id(investigation_id: str) -> str:
    if not isinstance(investigation_id, str) or not _INVESTIGATION_ID_RE.match(
        investigation_id
    ):
        raise InvalidInvestigationId(
            f"investigation_id must match {_INVESTIGATION_ID_RE.pattern!r}; "
            f"got {investigation_id!r}"
        )
    return investigation_id


class AuditLog:
    """Append-only writer for one investigation's audit trail.

    Construct once per investigation; reuse across all skill runs. Concurrent
    appends from a single process are safe because each ``write`` opens the
    file in append mode and writes one ``\\n``-terminated line. Cross-process
    concurrency is out of scope — investigations are single-process per
    CLAUDE.md's harness model.
    """

    def __init__(
        self,
        investigation_id: str,
        *,
        base_dir: Path | str = DEFAULT_AUDIT_DIR,
    ) -> None:
        self.investigation_id = _validate_investigation_id(investigation_id)
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.base_dir / f"{self.investigation_id}.jsonl"

    def _write(self, kind: str, payload: Mapping[str, Any]) -> None:
        entry = {
            "ts": _utc_now_iso(),
            "investigation_id": self.investigation_id,
            "kind": kind,
            "payload": dict(payload),
        }
        line = json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def log_observation(
        self,
        note: Note,
        status: ObservationStatus,
        *,
        reason: str | None = None,
    ) -> None:
        """Record a verifier outcome for an emitted Note.

        ``status`` is the ``VerificationResult`` from the substring verifier
        (or any equivalent ObservationStatus). ``reason`` is a free-form note
        from the caller — required when status != PASS so the audit trail
        explains every non-pass outcome.
        """
        if status is not VerificationResult.PASS and not reason:
            raise AuditLogError(
                f"reason is required when status is {status!r} (no silent loss)"
            )
        self._write(
            "observation",
            {
                "status": status.value,
                "reason": reason,
                "note": note.model_dump(mode="json"),
            },
        )

    def log_drop(self, reason: str, context: Mapping[str, Any]) -> None:
        """Record a Note (or candidate) that was dropped before/instead of emission.

        ``reason`` MUST be non-empty — silent loss is the explicit failure mode
        we are guarding against.
        """
        if not reason or not reason.strip():
            raise AuditLogError("reason is required for drops (no silent loss)")
        self._write(
            "drop",
            {
                "reason": reason,
                "context": dict(context),
            },
        )

    def log_translation_failure(
        self,
        quote_meta: Mapping[str, Any],
        translator: str,
        error: str,
    ) -> None:
        """Record a translation failure for one quote.

        Per CLAUDE.md, translation failures don't drop the quote — the quote
        survives with ``quote_text_en=None`` and ``translator_of_record`` set
        to ``'<model>@<version>:translation_failed'``. This method records
        the underlying error so the audit trail still explains why the English
        side of the quote is missing. ``translator`` is the bare translator id
        (e.g. ``argos-1.9``); we add the canonical suffix here so callers
        cannot silently drift from the contract.
        """
        if not translator or not translator.strip():
            raise AuditLogError("translator is required (no silent loss)")
        if translator.endswith(TRANSLATION_FAILED_SUFFIX):
            raise AuditLogError(
                "pass the bare translator id; the ':translation_failed' suffix "
                "is appended by the audit writer"
            )
        if not error or not error.strip():
            raise AuditLogError("error description is required (no silent loss)")
        self._write(
            "translation_failure",
            {
                "translator_of_record": f"{translator}{TRANSLATION_FAILED_SUFFIX}",
                "error": error,
                "quote_meta": dict(quote_meta),
            },
        )

    @staticmethod
    def quote_meta(quote: Quote) -> dict[str, Any]:
        """Project a Quote down to the provenance subset used in audit entries.

        Excludes ``quote_text_en`` (which is None on failure anyway) so the
        audit log never claims an English translation that doesn't exist.
        """
        return {
            "doc_id": quote.doc_id,
            "page": quote.page,
            "char_offset_start": quote.char_offset_start,
            "char_offset_end": quote.char_offset_end,
            "extractor_version": quote.extractor_version,
            "normalized_text_sha256": quote.normalized_text_sha256,
            "source_lang": quote.source_lang,
        }
