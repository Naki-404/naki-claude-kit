---
description: Find untested code, write the missing behavior-first tests and report the coverage change
argument-hint: [path or module] [target coverage, default 80]
---

# /naki-tests

Find code without meaningful tests and add tests that protect its behavior. Change test files only.

## 1. Scope and rules

- Scope: the path in `$ARGUMENTS`, otherwise files changed on the current branch, otherwise the whole project.
- Target: the number in `$ARGUMENTS` if given, otherwise 80% line coverage for the scope. Coverage is a guide; risky
  logic matters more than the percentage.
- Read the project rules skill if present (for example `naki-myapp`). Respect limits on running tests that use paid
  APIs, GPUs or real data.

## 2. Measure

Run coverage for the scope:
- Python: `pytest --cov=<pkg> --cov-report=term-missing -q <tests>`
- Frontend: `npx vitest run --coverage`

Record the baseline. If tests fail before you start, report the failures and ask whether to continue.

## 3. Choose targets

Rank uncovered code by risk: business rules, validation and auth, data transformation, error paths, then the rest.
Skip generated code, trivial wrappers and framework configuration.

## 4. Write tests

Run the `naki-test-writer` agent with the ranked targets, the framework and the project's test conventions. For a
small scope, write the tests yourself with the same rules:

- One behavior per test, descriptive names, arrange-act-assert.
- Mock only at boundaries (network, clock, filesystem, paid APIs).
- Cover failure paths and edge cases, not only the happy path.
- Follow `naki-python-testing`, `naki-frontend-testing` or `naki-e2e-playwright` for the stack.
- If you find a bug, do not fix production code here; report it.

## 5. Verify

Run the new tests and the project's full test suite and linters. All must pass.

## 6. Report

```
## Test coverage
Scope: ...
Coverage: <before>% -> <after>% (target <T>%)
Tests added:
- tests/test_x.py::test_rejects_expired_token: <behavior>
Bugs found: ...
Still untested (and why): ...
```

Commit only when the user asks.
