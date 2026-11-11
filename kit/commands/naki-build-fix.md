---
description: Detect the build system and fix build, type and lint errors incrementally with minimal diffs
argument-hint: [failing command or path]
---

# /naki-build-fix

Get the build green with the smallest safe changes. No refactoring, no new features.

## 1. Detect

If `$ARGUMENTS` names a command, use it. Otherwise detect:

| Marker | Commands to try |
|---|---|
| `pyproject.toml`, `requirements*.txt` | `ruff check .`, `mypy` or `pyright` if configured, `pytest -q` |
| `package.json` | scripts `build`, `typecheck`, `lint`; package manager from the lockfile |
| `Makefile` | `make build`, `make lint`, `make test` targets if present |
| `Dockerfile` | `docker build` only if the user asks (it can be slow) |

Read the project rules skill if present (for example `naki-myapp`); it may define the exact commands and which
tests are safe to run.

## 2. Reproduce

Run the failing command. Save the error count and the first errors. If it passes, report that and stop.

## 3. Fix

For more than a handful of errors, or errors across several files, run the `naki-build-fixer` agent with the command
and output. For a few local errors, fix them yourself using the same rules:

- Fix root causes first; one bad import can cause many errors.
- Smallest correct change. Avoid `any`, casts, `# type: ignore`, `eslint-disable` and `noqa` unless the error is a
  tool limitation, and add a short reason when used.
- Never delete or skip tests, never loosen compiler or linter config globally.
- Re-run the command after each group of fixes and confirm the error count drops.

## 4. Stop and ask when

- A fix changes a public API, schema or user-visible behavior.
- A dependency needs adding, removing or a major upgrade.
- The same error persists after three attempts.
- A guard hook blocks an action with a `kit:` reason. Follow the reason and ask; do not work around it.

## 5. Verify

Run the project's tests and linters after the build passes, at least for touched modules.

## 6. Report

```
## Build fix
Command: ...
Before: N errors | After: N errors
Changes:
- file:line: <change> (<reason>)
Tests / lint: <results>
Needs decision: ...
```

Commit only when the user asks.
