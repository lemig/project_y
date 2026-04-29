# Dependency decision: `followthemoney`

**Date:** 2026-04-29
**Reviewer:** Miguel Cabero (lemig)
**Status:** Cleared for import — recommend adopting as a dependency.

## Package

- **Name:** `followthemoney`
- **PyPI:** https://pypi.org/project/followthemoney/
- **Repo:** https://github.com/alephdata/followthemoney
- **Role in project_y:** Canonical FtM data model (entity schemas, validators, statement
  serialization). Used to construct and validate FtM entities returned by the Aleph REST
  API and emitted by our own extractors before audit-log write.

## License (verbatim header)

From `LICENSE` at https://github.com/alephdata/followthemoney/blob/main/LICENSE:

> ```
> MIT License
>
> Copyright (c) 2017-2024 Journalism Development Network, Inc.
> ```

PyPI metadata classifier: `License :: OSI Approved :: MIT License` (matches the repo
LICENSE file).

## Compatibility verdict

| Outbound license for project_y | Compatible? | Notes |
|--------------------------------|-------------|-------|
| Apache 2.0                     | ✅          | MIT → Apache 2.0 is a textbook permissive-into-permissive case. MIT terms are a strict subset of Apache 2.0 obligations; we keep the MIT notice and copyright in `NOTICE`/distribution and we are clear. |
| EUPL v1.2                      | ✅          | MIT is permissive (not reciprocal) and is recognised by the European Commission as compatible-as-inbound with EUPL v1.2: MIT-licensed code can be reused, linked, merged, and redistributed inside an EUPL outbound work. |
| **Both (we have not yet picked an outbound)** | ✅ | Importing `followthemoney` does not constrain our future EUPL-vs-Apache choice. |

Reference: European Commission's Interoperable Europe Portal compatibility checker
[MIT (inbound) → EUPL-1.2 (outbound)](https://interoperable-europe.ec.europa.eu/licence/compatibility-check/MIT/EUPL-1.2).

## Recommendation

**Import `followthemoney` as a runtime dependency.** Do not roll our own FtM validator
subset. The library *is* the FtM data model — re-implementing schemas, property types,
and validators in pure Python would duplicate ~5k lines of public, well-maintained code,
diverge silently when Aleph upstream evolves the model, and undermine our claim that
project_y produces FtM-conformant output. Crucially, `followthemoney` is **MIT** and
therefore *not* part of the AGPL ring fence we apply to the rest of the OpenAleph stack
(`ftm-analyze`, `ingest-file`, `openaleph-procrastinate`, `ftm-translate`,
`ftm-lakehouse`) — those remain REST-only.

## Rationale

The MIT License grants unrestricted rights to "use, copy, modify, merge, publish,
distribute, sublicense, and/or sell" the software, conditioned only on retention of the
copyright notice and license text. Apache 2.0's obligations (notice file, change
markers, patent grant) are a strict superset of MIT's, so an Apache-2.0 outbound for
project_y absorbs MIT inbound code cleanly — we just preserve the MIT header in the
distribution. EUPL v1.2 is a reciprocal license whose Article 5 compatibility clause
applies to *reciprocal* compatible licenses listed in its Appendix; MIT, being
permissive, sits outside that clause but is permitted as **inbound** code under the
EUPL because nothing in MIT conflicts with EUPL's copyleft obligations on the combined
work — we simply carry the MIT notice forward and the combined derivative is
distributable under EUPL. Either outbound choice is therefore safe, and the dependency
imposes no decision pressure on the EUPL-vs-Apache call deferred to publication time.

## Action

- [x] License cleared.
- [ ] Workspace C to add `followthemoney` to `pyproject.toml` (this review does not
      modify dependency manifests — that's their call).
- [ ] On adoption: include MIT notice + copyright in project_y's distribution NOTICE
      file (whichever outbound license we pick).
