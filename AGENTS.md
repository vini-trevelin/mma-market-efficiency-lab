# Agent Operating Instructions

This repository uses the detailed workflow in
[`docs/repository-guide.md`](docs/repository-guide.md). Read that file before
planning or editing code.

Minimum context to load before non-trivial work:

1. `AGENTS.md`
2. `docs/repository-guide.md`
3. `docs/sources.md`
4. `tasks/todo.md`
5. Relevant config, source, and tests

Use `tasks/todo.md` as the task log. Add a short plan before implementation,
keep checkable items current, and add verification results when done.

Core rules:

- Treat the user as architect and do not silently expand scope.
- Prefer simple, surgical changes over rewrites or speculative abstractions.
- Preserve point-in-time correctness, timestamp alignment, deterministic behavior,
  and diagnosable failures.
- Run relevant tests for every behavior change.
- Do not mutate local warehouse/raw data unless the task explicitly requires it.
- Do not run destructive, production-impacting, credential, or external-side-effect
  actions without explicit approval.
