# project_y

Audit-grade AI investigator built on top of OpenAleph. OLAF-internal program, intended for inter-agency adoption across OLAF's anti-fraud collaboration network.

Conference target: 2-day workshop in Limassol, Cyprus, 23-24 June 2026.

## Quick start (dev)

```bash
bin/dev-init      # one-time setup: ports, env files, aleph secret
bin/dev-up        # start the Aleph stack (Postgres + Elasticsearch + Redis + workers)
bin/dev-status    # see what's running and on which ports
bin/dev-down      # stop (preserves volumes; pass --purge to also drop them)
```

The dev environment uses **remote LLM inference** (OpenRouter or Google Cloud Vertex serving Gemma 4) configured via env vars in `server/.env`. No vLLM/GPU required for development. vLLM on-prem deployment lands post-conference for real OLAF case dogfood (weeks 9-10).

## Conductor parallel-workspace pattern

Each Conductor workspace gets its own port-offset Aleph stack so multiple workspaces can run simultaneously without collision:

| Offset | Service                                              |
|--------|------------------------------------------------------|
| +0     | **Aleph UI** ← what you open in the browser          |
| +1     | Aleph API ← what project_y will talk to              |
| +2     | project_y API (reserved)                             |
| +3     | project_y dev UI (reserved)                          |
| +10    | Aleph Postgres                                       |
| +11    | Aleph Elasticsearch                                  |
| +12    | Aleph Redis                                          |

Base port comes from `CONDUCTOR_PORT` (set by Conductor per workspace; defaults to 8000 if unset). Containers + Docker volumes are isolated per workspace via `COMPOSE_PROJECT_NAME=project_y-${API_PORT}`.

`server/.env` symlinks to `~/projects/project_y/server/.env` if it exists, so secrets like `LLM_API_KEY` are shared across workspaces without duplication. Falls back to copying `server/.env.example` if the shared location is empty.

## Architecture

See the design doc at `~/.gstack/projects/lemig-project_y/cabermi-aleph-investigator-design-20260427-213606.md` and the strategic plan at `~/.gstack/projects/lemig-project_y/ceo-plans/2026-04-27-aleph-investigator-v2.md`.

Short version:
- **Substrate:** OpenAleph + Follow the Money data model (REST API only; no AGPL imports).
- **Harness:** Deep Agents (Apache 2.0, pinned) wrapped behind an internal `AgentHarness` adapter for swappability.
- **Skills:** Investigative methodology as markdown SKILL.md files with YAML frontmatter (resolver + verifier + tests). Skillify protocol borrowed from GBrain as methodology, not as a code dependency.
- **Determinism:** Substring quote verifier + FtM validators + audit log are pure deterministic Python — where trust lives.
- **Audit trail:** Every observation note backed by at least one exact quote with full provenance (doc_id, page, char_offset, extractor_version, normalized_text_sha256). Substring verification is a hard generation-time gate.
- **Multilingual:** Source-language quote + English translation + translator_of_record. Survives Aleph re-OCR.

## License

Closed-source for now. Sharing-ready architecture (every dependency must be both EUPL-compatible AND Apache-compatible). Final license decision is deferred to publication time and belongs to DG INFORMATICS / Commission OSS publication policy.
