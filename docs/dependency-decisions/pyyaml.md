# Dependency decision: `pyyaml`

**Date:** 2026-04-29
**Reviewer:** Miguel Cabero (lemig)
**Status:** Cleared for import — pinned at `pyyaml==6.0.3`.

## Package

- **Name:** `pyyaml`
- **PyPI:** https://pypi.org/project/PyYAML/
- **Repo:** https://github.com/yaml/pyyaml
- **Role in project_y:** Parses the YAML frontmatter block at the top of every
  `SKILL.md` file inside `DeepAgentsHarness.load_skill`. Pulled in transitively
  by `langchain` already; we promote it to a direct dependency so the harness
  is honest about what it imports and so a future `langchain` change cannot
  silently drop it.

## License

PyPI metadata classifier: `License :: OSI Approved :: MIT License`. The repo
`LICENSE` file at https://github.com/yaml/pyyaml/blob/main/LICENSE is the
standard MIT text.

## Compatibility verdict

| Outbound license for project_y | Compatible? |
|--------------------------------|-------------|
| Apache 2.0                     | ✅          |
| EUPL v1.2                      | ✅          |

Same reasoning as `followthemoney` and `deepagents`: MIT is a strict subset of
Apache 2.0 obligations and is recognised by the European Commission as
compatible-as-inbound with EUPL v1.2. Importing `pyyaml` does not constrain
the EUPL-vs-Apache outbound choice deferred to publication time.

## Why `safe_load`

We only ever call `yaml.safe_load` on `SKILL.md` frontmatter — never
`yaml.load`. `safe_load` rejects YAML's tag-based object construction
machinery (the historical CVE surface) and limits parsing to plain scalars,
mappings, and sequences — which is all the frontmatter schema needs. Inputs
are checked-in markdown files we author and review, but we still apply
`safe_load` as defence-in-depth in case a skill file is ever sourced from a
less-trusted path in v3.

## Action

- [x] License cleared.
- [x] Pinned exactly in `pyproject.toml`.
- [ ] On distribution: include MIT notice + Ingy döt Net / Kirill Simonov
      copyright in project_y's `NOTICE` file.
