"""LLM eval for detect-procurement-collusion.

Sends the SKILL.md methodology body + a synthetic procurement corpus + a
brief to the configured LLM endpoint and asserts that the response surfaces
the bid-rigging signal families seeded in the fixtures.

This is an LLM eval (Skillify protocol step in CLAUDE.md, premise 3) — not a
trust-path component. It does NOT exercise the substring quote verifier
(out of scope for this skill PR; lives in `src/verifier/substring.py` and is
gated by `tests/test_substring_verifier.py`). It DOES verify that the
methodology body, when passed to the LLM that the harness will eventually
spawn, drives the model toward the right detections.

Skipped unless `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` are all set —
matches the convention in `tests/test_deep_agents_integration.py`. Marked
`integration` so the default `pytest -m "not integration"` skips it on
offline workstations and pre-merge CI without a model endpoint.

The eval threshold is 3-of-4 signal families (rather than 4-of-4) to keep
the test stable across model temperature and provider drift while still
failing loudly if the methodology body regresses. Calibrate up to 4-of-4
once the LLM endpoint is pinned for golden-run replay (CLAUDE.md, premise 2).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

_SKILL_DIR = Path(__file__).resolve().parents[1]
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_FIXTURES = _SKILL_DIR / "tests" / "fixtures"

_REQUIRED_ENV = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")
_MIN_FAMILIES_DETECTED = 3
_LLM_TIMEOUT_S = 90.0

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not all(k in os.environ for k in _REQUIRED_ENV),
        reason=(
            "Set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL to run the "
            "detect-procurement-collusion LLM eval."
        ),
    ),
]


def _read_skill_body() -> str:
    raw = _SKILL_MD.read_text(encoding="utf-8")
    end = raw.find("\n---\n", len("---\n"))
    return raw[end + len("\n---\n") :]


def _read_corpus() -> str:
    chunks: list[str] = []
    for doc in sorted(_FIXTURES.glob("*.txt")):
        if doc.name == "brief.txt":
            continue
        chunks.append(f"=== DOC_ID: {doc.stem} ===\n{doc.read_text(encoding='utf-8')}")
    return "\n\n".join(chunks)


def _read_brief() -> str:
    return (_FIXTURES / "brief.txt").read_text(encoding="utf-8").strip()


def _read_expected() -> dict[str, Any]:
    return json.loads((_FIXTURES / "expected_signals.json").read_text(encoding="utf-8"))


def _build_prompt() -> str:
    return (
        "You are following the methodology defined in the SKILL.md below. "
        "Read the corpus, then output a JSON object with a single key "
        '"signals" whose value is a list of objects, each with "claim" '
        '(one sentence describing the signal) and "family" (one of: '
        '"rotation", "common_ownership", "narrow_specs", '
        '"identical_clerical_errors", "complementary_bidding", '
        '"timing", "subcontracting", "single_source"). Output JSON only — '
        "no prose, no code fences.\n\n"
        "=== SKILL METHODOLOGY ===\n"
        f"{_read_skill_body()}\n\n"
        "=== BRIEF ===\n"
        f"{_read_brief()}\n\n"
        "=== CORPUS ===\n"
        f"{_read_corpus()}\n"
    )


def _call_llm(prompt: str) -> str:
    """Same construction path as `agent.deep_agents_harness` — `ChatOpenAI`
    against the env-configured OpenAI-compatible endpoint. Keeps the LLM
    eval honest about what the harness will actually drive in production."""
    from langchain_openai import ChatOpenAI  # local import: optional dep at test time

    model = ChatOpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        model=os.environ["LLM_MODEL"],
        temperature=0.0,
        timeout=_LLM_TIMEOUT_S,
    )
    response = model.invoke(prompt)
    return response.content if isinstance(response.content, str) else str(response.content)


def _parse_signals(raw: str) -> list[dict[str, str]]:
    text = raw.strip()
    # Some endpoints still wrap JSON in fences despite the instruction.
    if text.startswith("```"):
        text = text.strip("`")
        # Drop any leading 'json' language tag.
        first_newline = text.find("\n")
        if first_newline != -1 and not text[:first_newline].strip().startswith("{"):
            text = text[first_newline + 1 :]
        text = text.rstrip("`").strip()
    payload = json.loads(text)
    signals = payload.get("signals")
    if not isinstance(signals, list):
        raise AssertionError(f"LLM response missing 'signals' list: {payload!r}")
    return [s for s in signals if isinstance(s, dict)]


def test_skill_surfaces_seeded_signal_families() -> None:
    expected = _read_expected()
    families: dict[str, list[str]] = expected["expected_families"]

    raw = _call_llm(_build_prompt())
    signals = _parse_signals(raw)
    assert signals, "LLM returned zero signals; methodology body likely broken"

    haystack = " ".join(
        f"{s.get('family', '')} {s.get('claim', '')}" for s in signals
    ).lower()

    detected = {
        family
        for family, keywords in families.items()
        if any(kw.lower() in haystack for kw in keywords)
    }

    assert len(detected) >= _MIN_FAMILIES_DETECTED, (
        f"LLM detected only {len(detected)} of {len(families)} seeded signal "
        f"families: detected={sorted(detected)}, expected at least "
        f"{_MIN_FAMILIES_DETECTED} of {sorted(families)}. Raw LLM output:\n{raw}"
    )
