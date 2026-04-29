# Dependency decision: `deepagents`

**Date:** 2026-04-29
**Reviewer:** Miguel Cabero (lemig)
**Status:** Cleared for import — recommend adopting at exact-pinned `deepagents==0.4.12`.

## Package

- **Name:** `deepagents`
- **PyPI:** https://pypi.org/project/deepagents/
- **Repo:** https://github.com/langchain-ai/deepagents
- **Version under review:** `0.4.12` (latest stable on PyPI as of this review)
- **Role in project_y:** Backing runtime for the `AgentHarness` ABC defined in
  `src/agent/harness.py`. `DeepAgentsHarness` (this workspace) is the only code
  in the project that imports `deepagents` directly; skills, the audit log, the
  verifier, and the REST client all sit behind the ABC.

## License (verbatim)

From `LICENSE` at https://github.com/langchain-ai/deepagents/blob/main/LICENSE:

> ```
> MIT License
>
> Copyright (c) LangChain, Inc.
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to
> deal in the Software without restriction, including without limitation the
> rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
> sell copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
> ```

PyPI metadata classifier: `License :: OSI Approved :: MIT License` (matches the
repo `LICENSE` file).

## Compatibility verdict

| Outbound license for project_y | Compatible? | Notes |
|--------------------------------|-------------|-------|
| Apache 2.0                     | ✅          | MIT → Apache 2.0 is permissive-into-permissive. We carry the MIT notice + LangChain copyright in `NOTICE`/distribution and we are clear. |
| EUPL v1.2                      | ✅          | MIT, being permissive (not reciprocal), is recognised by the European Commission as compatible-as-inbound with EUPL v1.2: MIT-licensed code can be reused, linked, merged, and redistributed inside an EUPL outbound work. Same reasoning we used for `followthemoney`. |
| **Both (we have not yet picked an outbound)** | ✅ | Importing `deepagents` does not constrain our future EUPL-vs-Apache choice. |

Reference: European Commission's Interoperable Europe Portal compatibility
checker
[MIT (inbound) → EUPL-1.2 (outbound)](https://interoperable-europe.ec.europa.eu/licence/compatibility-check/MIT/EUPL-1.2).

## Transitive dependencies

`deepagents==0.4.12` requires (per its PyPI metadata):

| Package                  | License | EUPL/Apache compatible? |
|--------------------------|---------|-------------------------|
| `langchain-core`         | MIT     | ✅                      |
| `langchain`              | MIT     | ✅                      |
| `langchain-anthropic`    | MIT     | ✅                      |
| `langchain-google-genai` | MIT     | ✅                      |
| `langsmith`              | MIT     | ✅                      |
| `wcmatch`                | MIT     | ✅                      |

We also pull in `langchain-openai==1.2.1` (MIT) so `DeepAgentsHarness` can
target any OpenAI-compatible endpoint (OpenRouter for dev, vLLM for OLAF
prod) with a single env-var swap, per CLAUDE.md.

None of the above are AGPL — the AGPL ring fence (`ftm-analyze`,
`ingest-file`, `openaleph-procrastinate`, `ftm-translate`, `ftm-lakehouse`)
remains REST-only.

## Why an exact pin (no `^` or `~`)

CLAUDE.md mandates: *"Pinned exact version. Golden-run replay tests gate dep
upgrades."* The harness adapter is the only project module that reaches into
`deepagents`'s API, but the agent's prompt-assembly behavior, tool selection,
and middleware ordering are all observable in the deterministic fields of the
golden run (skill load order, dispatched skill_ids, checkpoint contents).
A floating spec would let a transitive bump silently change planner routing
and break the audit trail without any code change of ours. Exact pin +
golden-run replay = controlled upgrade path: bump the pin, regenerate the
golden, review the diff, land the bump as its own commit.

## Recommendation

**Adopt `deepagents==0.4.12`** with `langchain-openai==1.2.1` as the model
adapter. Wire only through `src/agent/deep_agents_harness.py`. No other
project module imports `deepagents` directly.

## Action

- [x] License cleared (MIT, both EUPL v1.2 and Apache 2.0 compatible).
- [x] Version pinned exactly in `pyproject.toml`.
- [x] Golden-run replay tests added (`tests/test_deep_agents_golden.py`)
      so any future bump triggers a CI diff review.
- [ ] On distribution: include MIT notice + LangChain, Inc. copyright in
      project_y's `NOTICE` file (whichever outbound license we pick).
