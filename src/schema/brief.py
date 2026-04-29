"""Brief — the user-facing investigation request, bound to a corpus snapshot."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _nfc(s: str) -> str:
    """NFC-normalize so 'café' (U+00E9) and 'cafe\\u0301' (U+0301) hash equal.

    ~80% of OLAF cases are non-English. Without NFC, copy-paste / OCR /
    input-method drift produces visually-identical briefs that hash to
    different keys, silently orphaning notes from their parent investigation.
    """
    return unicodedata.normalize("NFC", s)


class Brief(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    corpus_snapshot_hash: str
    locale: str = Field(default="en", pattern=r"^[a-z]{2}$")

    @field_validator("text")
    @classmethod
    def _v_text(cls, v: str) -> str:
        return _nfc(v)

    @field_validator("corpus_snapshot_hash")
    @classmethod
    def _v_sha(cls, v: str) -> str:
        if not _SHA256_HEX_RE.match(v):
            raise ValueError("corpus_snapshot_hash must be 64 lowercase hex chars (sha256)")
        return v

    def compute_hash(self) -> str:
        """Canonical sha256 of the brief content. Used for Note.brief_hash."""
        payload = json.dumps(
            {
                "text": _nfc(self.text),
                "corpus_snapshot_hash": self.corpus_snapshot_hash,
                "locale": self.locale,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
