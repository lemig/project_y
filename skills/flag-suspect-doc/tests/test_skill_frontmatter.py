"""Frontmatter validation for skills/flag-suspect-doc/SKILL.md.

Pins the seven required keys, ensures the resolver regex compiles, ensures
output_schema_ref points at a real, importable schema, and ensures the body
isn't empty. These are the bits the harness assumes when loading a skill.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from skills.skill import SkillFrontmatter

from ._frontmatter import parse_skill_md

_SKILL_DIR = Path(__file__).resolve().parents[1]
_SKILL_MD = _SKILL_DIR / "SKILL.md"

_REQUIRED_KEYS = {
    "name",
    "version",
    "owner",
    "resolver",
    "output_schema_ref",
    "verifier",
    "tests_dir",
}


@pytest.fixture(scope="module")
def parsed() -> tuple[dict[str, str], str]:
    return parse_skill_md(_SKILL_MD)


class TestFrontmatter:
    def test_skill_md_exists(self) -> None:
        assert _SKILL_MD.is_file(), f"missing {_SKILL_MD}"

    def test_all_seven_keys_present(self, parsed: tuple[dict[str, str], str]) -> None:
        fm, _ = parsed
        assert set(fm.keys()) == _REQUIRED_KEYS, (
            f"frontmatter keys mismatch: extra={set(fm) - _REQUIRED_KEYS}, "
            f"missing={_REQUIRED_KEYS - set(fm)}"
        )

    def test_validates_against_pydantic_model(self, parsed: tuple[dict[str, str], str]) -> None:
        fm, _ = parsed
        # Round-trip through the locked SkillFrontmatter model — same gate
        # the harness will use at load time.
        model = SkillFrontmatter(**fm)
        assert model.name == "flag-suspect-doc"
        assert model.version == "v1"
        assert model.tests_dir == "skills/flag-suspect-doc/tests"

    def test_resolver_compiles(self, parsed: tuple[dict[str, str], str]) -> None:
        fm, _ = parsed
        # Must compile as a Python regex; the planner uses re.search() on it.
        re.compile(fm["resolver"])

    def test_output_schema_ref_resolves(self, parsed: tuple[dict[str, str], str]) -> None:
        fm, _ = parsed
        # output_schema_ref is "module.path.AttrName" — confirm it imports
        # and points to a Note-shaped class. Catches typos like
        # "schema.notes.Note" or stale renames before the harness sees them.
        ref = fm["output_schema_ref"]
        module_path, _, attr = ref.rpartition(".")
        assert module_path and attr, f"output_schema_ref must be 'module.Attr', got {ref!r}"
        module = importlib.import_module(module_path)
        cls = getattr(module, attr)
        assert hasattr(cls, "model_fields"), f"{ref} is not a pydantic BaseModel"
        assert "exact_quotes" in cls.model_fields, (
            f"{ref} does not look like the v2 Note (no exact_quotes field)"
        )

    def test_tests_dir_points_at_self(self, parsed: tuple[dict[str, str], str]) -> None:
        fm, _ = parsed
        # tests_dir is repo-relative; this test file lives inside it.
        repo_root = _SKILL_DIR.parents[1]
        declared = (repo_root / fm["tests_dir"]).resolve()
        assert declared == Path(__file__).resolve().parent

    def test_owner_is_olaf_address(self, parsed: tuple[dict[str, str], str]) -> None:
        fm, _ = parsed
        # Soft contract: owners on OLAF skills carry an @olaf.eu address.
        # If this changes (external contributor, etc.) flip the assertion
        # rather than letting it silently drift.
        assert fm["owner"].endswith("@olaf.eu"), f"unexpected owner: {fm['owner']!r}"

    def test_body_is_substantive(self, parsed: tuple[dict[str, str], str]) -> None:
        _, body = parsed
        # Methodology body must actually contain methodology — not be a stub.
        assert len(body.strip()) > 1000, "SKILL.md body is suspiciously short"

    def test_body_references_audit_invariants(self, parsed: tuple[dict[str, str], str]) -> None:
        _, body = parsed
        # The methodology must instruct the agent to honour the v2 audit
        # contract that the harness, verifier, and Note schema enforce.
        # Phrasing the assertion at the contract level (not at exact wording)
        # so methodology copy can evolve without breaking these tests.
        lower = body.lower()
        assert "exact_quotes" in body, "body must mention exact_quotes"
        assert "verbatim" in lower, "body must require verbatim quotes"
        assert "translator_of_record" in body, "body must address translation provenance"
        assert "translation_failed" in lower, "body must state the translation-failure marker"
        assert "confidence" in lower, "body must explain how confidence is assigned"

    def test_body_cites_public_sources_only(
        self, parsed: tuple[dict[str, str], str]
    ) -> None:
        _, body = parsed
        # CLAUDE.md rule: skills draw from PUBLIC investigative methodology.
        # Sanity-check that a Sources block exists and references at least
        # the canonical public bodies named in the methodology.
        lower = body.lower()
        assert "sources" in lower, "body must include a Sources section"
        for citation in ("acfe", "fatf", "oecd"):
            assert citation in lower, f"body must cite {citation.upper()}"
