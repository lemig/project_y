# project_y — Claude Code project context

This file gives Claude Code full context on subsequent sessions. Read it first.

## What this project is

**project_y is an audit-grade AI investigator built on OpenAleph + Follow the Money, developed at OLAF as an internal program for inter-agency adoption across OLAF's collaboration network.** Not a startup. Not commercial. OLAF owns the IP. Eventually published as open source under whichever Commission-authorised license applies (EUPL v1.2 or Apache 2.0; decision deferred to publication time).

Conference target: 2-day workshop, Limassol, Cyprus, 23-24 June 2026 (~8 weeks from project start). Audience: analysts + managers + few tech from Belgian MinFin, Guardia di Finanza, Eurojust, Italian Customs, FIU.NET, other partner agencies.

Recurring channel: yearly conference + quarterly online meetings + structured exchange of deliverables (tools applications) within OLAF's anti-fraud collaboration network.

## Architectural premises (LOCKED across 9 review rounds — do not reopen lightly)

1. **Substrate:** OpenAleph + FtM. REST API only — never `import` AGPL packages (`ftm-analyze`, `ingest-file`, `openaleph-procrastinate`, `ftm-translate`, `ftm-lakehouse`). Use `followthemoney` Python lib only if its license is MIT/Apache (verify in Pre-Week-1).
2. **Harness:** Deep Agents (LangChain, MIT — see `docs/dependency-decisions/deep-agents.md`). Wrapped behind an internal `AgentHarness` adapter (`src/agent/harness.py`) exposing a stable interface (`planner_run`, `spawn_subagent`, `load_skill`, `checkpoint`, `resume`). Concrete adapter at `src/agent/deep_agents_harness.py`. Pinned exact version (`deepagents==0.4.12`). Golden-run replay tests gate dep upgrades.
3. **Skills:** Investigative methodology as markdown SKILL.md files in `skills/`. YAML frontmatter (name / version / owner / resolver / output_schema_ref / verifier / tests_dir). Skillify 10-step protocol borrowed from GBrain as METHODOLOGY (not code dependency). Hermes/GBrain not adopted as deps — GEPA self-modification incompatible with court-defensibility.
4. **Determinism:** Substring quote verifier + FtM validators + audit log writer + Aleph REST client are pure deterministic Python. No LLM in the trust path.
5. **Audit trail:** Every observation note has `exact_quotes` with `(doc_id, page, char_offset_start, char_offset_end, extractor_version, normalized_text_sha256, quote_text, quote_text_en, translator_of_record)`. Substring verifier is a HARD generation-time gate; 3-retry then drop+log on failure. Silent loss unacceptable.
6. **Multilingual from day 0:** ~80% of OLAF cases are non-English. UI is English-only. Source-language quote + English translation alongside.
7. **Two-tier notes (mandate + investigation):** v2 ships investigation-only; mandate behavior in v3.
8. **Per-investigation corpus snapshot:** native Aleph snapshot if Spike 1 succeeds, else manifest+hash fallback.
9. **6 hard-gated bug-class tests:** ranking-regression, planner-drift-on-dep-bump, near-quote-adversarial, checkpoint-corruption, cross-skill-conflict, fluent-bad-translation.

## v2 starter skills (build these first, week 1-2)

1. `find-money-flow.md` — trace funds across docs/entities given a starting account or contract.
2. `detect-procurement-collusion.md` — pattern-match for tender-rigging signals.
3. `cross-reference-pep.md` — entity → public PEP/sanctions list lookup. v2: placeholder. v3: full integration with OpenSanctions bulk index.
4. `find-shell-companies.md` — registration patterns + ownership opacity scoring.
5. `narrate-fraud-pattern.md` — assemble grounded notes into 1-page narrative.
6. `summarize-by-entity.md` — per-entity summary across all docs mentioning them.
7. `flag-suspect-doc.md` — preserve v1's working primitive (rank docs by fraud-likelihood) as a skill.

## Note schema (v2)

```python
{
  "claim": str,
  "exact_quotes": [
    {
      "quote_text": str,           # source-language verbatim
      "quote_text_en": str | None, # English translation (None if source is EN)
      "doc_id": str,
      "page": int | None,           # 1-based; None for non-paginated
      "char_offset_start": int,
      "char_offset_end": int,
      "extractor_version": str,    # e.g., "tesseract-5.3.1@aleph-3.18"
      "normalized_text_sha256": str,
      "source_lang": str,          # ISO-639-1
      "translator_of_record": str | None,
    }
  ],
  "confidence": float,
  "why_relevant": str,
  "tier": "investigation",  # mandate-tier deferred to v3
  "source_corpus_snapshot_hash": str,
  "brief_hash": str,
  "skill_id": str,           # e.g., "find-money-flow@v1"
  "skill_resolver_match": str,
  "skill_version": str,      # git SHA of the skill markdown file at run time
}
```

## Dev environment

LLM is endpoint-configurable via env vars (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`). Same code, different endpoints:
- **Dev / conference demo (weeks 1-8):** OpenRouter or Google Cloud Vertex serving Gemma 4. From dev workstation. No GPU required.
- **OLAF prod (weeks 9+):** OLAF Linux backend with 6x NVIDIA L40S, vLLM serving Gemma 4 via OpenAI-compatible endpoint. Air-gapped. Same code; only the endpoint URL changes.

vLLM deployment is **post-conference** work. Don't add vLLM containers to dev docker-compose pre-conference.

## Conductor parallel workspaces

Each workspace gets a per-workspace port-offset Aleph stack via `bin/dev-init` reading `CONDUCTOR_PORT` env var. Distinct `COMPOSE_PROJECT_NAME` per workspace = container + volume isolation. `server/.env` symlinks to `~/projects/project_y/server/.env` if present; falls back to copying `server/.env.example`.

## Critical rules

- **No AGPL Python imports.** Talk to Aleph via REST API only. Verify license of any new dependency for compatibility with both EUPL and Apache before adding.
- **No `except Exception:`.** Name specific exception classes per Aleph error type. Log with full context.
- **No silent loss in the audit log.** Every dropped note logs the reason. Every translation failure logs `translator_of_record: "<model>@<version>:translation_failed"` and continues with `quote_text_en: null`.
- **Every dependency upgrade triggers golden-run replay tests.** If output drifts, CI fails.
- **No skill writes investigative methodology that's OLAF-internal.** Skills are written from PUBLIC investigative methodology (textbooks, ACFE, IRE training, public KYC literature). OLAF-specific operational details stay out.
- **Skillify protocol applies to every skill.** Each skill has: YAML frontmatter (name / version / owner / resolver / schema / verifier / tests) + unit tests + integration test + LLM eval + resolver eval + DRY audit entry. No exceptions.

## Skill routing for Claude Code (gstack)

When the user's request matches a gstack skill, invoke it. Key routing:
- Brainstorming, "is this worth building" → `/office-hours`
- Strategy, scope, "think bigger" → `/plan-ceo-review`
- Architecture, "does this design make sense" → `/plan-eng-review`
- UI/UX review of plan → `/plan-design-review`
- Implementation review of diff → `/review`
- Bugs, "why is this broken" → `/investigate`
- Test the site, "does this work" → `/qa`
- Ship/PR/deploy → `/ship`
- Save / restore session context → `/context-save` / `/context-restore`

The auto-memory at `~/.claude/projects/-Users-cabermi-conductor-repos-project-y/memory/` persists user + project + reference info across sessions.

## Authoritative artifacts

- **Design doc:** `~/.gstack/projects/lemig-project_y/cabermi-aleph-investigator-design-20260427-213606.md`
- **Strategic / CEO plan:** `~/.gstack/projects/lemig-project_y/ceo-plans/2026-04-27-aleph-investigator-v2.md`
- **Test plan (for /qa):** `~/.gstack/projects/lemig-project_y/cabermi-aleph-investigator-eng-review-test-plan-20260428-003121.md`
- **OpenAleph reference repo:** `~/conductor/repos/openaleph` (read for substrate behavior; do NOT import the AGPL packages directly)
- **v1 reference (project_x):** `~/conductor/repos/project_x` (Miguel's prior implementation; OLAF IP; v2 is built clean from the design doc, not by lifting from v1)
