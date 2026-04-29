"""Note + Quote — the v2 audit record. Locked across 9 review rounds (see CLAUDE.md).

Every observation a skill produces is a Note; every Note carries at least one
Quote with full provenance. Models are frozen and reject unknown fields so the
audit trail stays canonical.

Layering note: this schema enforces structural invariants only. Binding
`quote_text` to its (doc_id, char_offset_*, normalized_text_sha256) tuple is
the substring quote verifier's job — a separate, deterministic, pure-Python
component that reads the document at generation time and is the hard gate per
CLAUDE.md. The schema has no document at validation time and must not pretend
to.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ISO_639_1_RE = re.compile(r"^[a-z]{2}$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA1_HEX_RE = re.compile(r"^[0-9a-f]{40}$")
_TRANSLATION_FAILED_SUFFIX = ":translation_failed"


def _validate_sha256(v: str) -> str:
    if not _SHA256_HEX_RE.match(v):
        raise ValueError("must be 64 lowercase hex chars (sha256)")
    return v


def _is_translation_failure_marker(translator: str) -> bool:
    """Strict suffix check with non-blank translator-id prefix.

    Rejects substring forgeries ('x:translation_failed-but-not-really'),
    the bare suffix (':translation_failed'), and whitespace-only prefixes
    (' :translation_failed').
    """
    if not translator.endswith(_TRANSLATION_FAILED_SUFFIX):
        return False
    prefix = translator[: -len(_TRANSLATION_FAILED_SUFFIX)]
    return bool(prefix.strip())


class Quote(BaseModel):
    """A verbatim source-language quote bound to its document position."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    quote_text: str = Field(min_length=1)
    quote_text_en: str | None = Field(default=None, min_length=1)
    doc_id: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    char_offset_start: int = Field(ge=0)
    char_offset_end: int = Field(ge=0)
    extractor_version: str = Field(min_length=1)
    normalized_text_sha256: str
    source_lang: str
    translator_of_record: str | None = Field(default=None, min_length=1)

    @field_validator("normalized_text_sha256")
    @classmethod
    def _v_sha(cls, v: str) -> str:
        return _validate_sha256(v)

    @field_validator("source_lang")
    @classmethod
    def _v_lang(cls, v: str) -> str:
        if not _ISO_639_1_RE.match(v):
            raise ValueError("source_lang must be a 2-letter ISO-639-1 code (lowercase)")
        return v

    @field_validator("quote_text_en", "translator_of_record")
    @classmethod
    def _v_non_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("must contain at least one non-whitespace character")
        return v

    @model_validator(mode="after")
    def _v_invariants(self) -> "Quote":
        if self.char_offset_end <= self.char_offset_start:
            raise ValueError("char_offset_end must be > char_offset_start")

        if self.source_lang == "en":
            if self.quote_text_en is not None:
                raise ValueError("quote_text_en must be None when source_lang is 'en'")
            if self.translator_of_record is not None:
                raise ValueError("translator_of_record must be None when source_lang is 'en'")
            return self

        # Non-English source: a translator_of_record is always required.
        if self.translator_of_record is None:
            raise ValueError(
                "translator_of_record is required when source_lang is not 'en' "
                "(use '<translator-id>:translation_failed' for failures)"
            )
        marker = _is_translation_failure_marker(self.translator_of_record)
        if self.quote_text_en is None and not marker:
            raise ValueError(
                "quote_text_en may be None only when translator_of_record is "
                "'<translator-id>:translation_failed' (exact suffix, non-empty prefix)"
            )
        if self.quote_text_en is not None and marker:
            raise ValueError(
                "translator_of_record carries the translation-failure suffix but "
                "quote_text_en is set; these are mutually exclusive"
            )
        return self


class Note(BaseModel):
    """An investigation note. Always backed by ≥1 Quote."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: str = Field(min_length=1)
    exact_quotes: tuple[Quote, ...] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    why_relevant: str = Field(min_length=1)
    tier: Literal["investigation"] = "investigation"
    source_corpus_snapshot_hash: str
    brief_hash: str
    skill_id: str = Field(min_length=1)
    skill_resolver_match: str = Field(min_length=1)
    skill_version: str

    @field_validator("source_corpus_snapshot_hash", "brief_hash")
    @classmethod
    def _v_sha(cls, v: str) -> str:
        return _validate_sha256(v)

    @field_validator("skill_version")
    @classmethod
    def _v_git_sha(cls, v: str) -> str:
        if not _GIT_SHA1_HEX_RE.match(v):
            raise ValueError("skill_version must be a 40-char lowercase hex git SHA-1")
        return v
