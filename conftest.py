"""Pre-bind `skills` namespace to src/skills/ so per-skill tests can import skill.SkillFrontmatter.

Without this, pytest's importlib mode collects test files under
`skills/<name>/tests/` and the project-root `skills/` directory shadows the
real `src/skills/` Python package — `from skills.skill import ...` fails with
ModuleNotFoundError.
"""
import skills as _skills_pkg  # noqa: F401  — force resolution to src/skills/
