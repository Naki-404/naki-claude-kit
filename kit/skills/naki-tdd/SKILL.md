---
name: naki-tdd
description: Test-first development loop: red, green, refactor in small steps, choosing the next test, fixing bugs by writing a failing reproduction first, and keeping tests fast and behavior-focused. Use when building a new feature or function, fixing a bug, refactoring risky code, or when the user asks for tests first.
---

# Test-driven development

Write a test that fails for the right reason, make it pass with the smallest change, then clean up while
green. Language-specific detail lives in `naki-python-testing` and `naki-frontend-testing`. Follow the
project rules skill if the project has one (for example `naki-myapp`).

## When to use

- New behavior with clear inputs and outputs (parsers, rules, scoring, API handlers, reducers).
- Every bug fix: reproduce with a failing test before touching the code.
- Refactors of code with weak coverage: add characterization tests first.
- Skip strict TDD for throwaway spikes and pure layout work; still add tests before the code is kept.

## Core rules

1. **No production code without a failing test that demands it.**
2. **Watch the test fail and read the failure.** It must fail on the assertion you expect, not on an import
   error or a typo. A test you never saw fail proves nothing.
3. **Make it pass with the simplest change.** Hard-coding is fine for one case; the next test forces
   generalization.
4. **Refactor only on green.** Run the tests after each refactor step.
5. **One behavior per step.** If a step takes longer than a few minutes, the step is too big; pick a smaller test.
6. **Test through the public interface.** Tests that poke private helpers break on every refactor.
7. **Keep the unit loop fast** (seconds). Run the focused test file during the loop, the full suite before
   declaring done.
8. **Do not change a test to make it pass** unless the test itself is wrong; say so explicitly when it is.
9. **Commit at green points** when the user wants commits; never commit red unless asked.

## The loop

```
RED      write one small failing test  -> run -> see the expected failure
GREEN    minimal code to pass          -> run -> all green
REFACTOR improve names, remove dupes   -> run -> still green
repeat
```

## Choosing the next test

Work from simple to complex:

1. Degenerate case (empty input, zero, none).
2. One simple valid case.
3. Variations that force generalization (two items, different types).
4. Boundaries (limits, off-by-one, max length, time zones).
5. Error cases (invalid input, dependency failure).

Keep a short test list in your notes; add ideas as they come, pick the one that teaches the most with the
least code.

## Bug fix workflow

1. Reproduce the bug manually or from the report; write down input, expected and actual output.
2. Write a test that encodes the expected behavior. Run it: it must fail the same way the bug does.
3. Fix the code. Run the test: green.
4. Run the full suite to catch regressions.
5. Ask: where else could the same mistake live? Add tests there if so.
6. Name the test after the behavior (`test_rejects_expired_token`), not the ticket number alone.

## Example (Python)

Step 1, red:

```python
from triage.score import severity_score

def test_unknown_source_scores_zero():
    assert severity_score({"source": "unknown", "hits": 0}) == 0
```

Run `pytest tests/test_score.py -q`: fails with `ModuleNotFoundError` first, so create the module with an
empty function and run again until the failure is the assertion.

Step 2, green:

```python
def severity_score(event: dict) -> int:
    return 0
```

Step 3, next test forces real logic:

```python
import pytest

@pytest.mark.parametrize("hits, expected", [(1, 10), (5, 50), (20, 100)])
def test_score_grows_with_hits_and_caps_at_100(hits, expected):
    assert severity_score({"source": "ids", "hits": hits}) == expected
```

```python
def severity_score(event: dict) -> int:
    if event["source"] == "unknown":
        return 0
    return min(event["hits"] * 10, 100)
```

Step 4, refactor: extract `MAX_SCORE = 100`, rerun, still green.

## Example (TypeScript, Vitest)

```ts
import { describe, expect, it } from "vitest";
import { parseDuration } from "./duration";

describe("parseDuration", () => {
  it("parses minutes", () => expect(parseDuration("15m")).toBe(900));
  it("rejects unknown units", () => expect(() => parseDuration("3y")).toThrow(/unit/));
});
```

## Test doubles

- Fake external boundaries (HTTP, clock, filesystem, message queues), not your own domain logic.
- Prefer fakes and in-memory implementations over deep mock chains.
- Inject dependencies (pass a clock or client) so tests do not need patching.

## Checklist

- [ ] Each new behavior started with a failing test that was observed failing.
- [ ] Failure message was the expected assertion.
- [ ] Bug fixes include a regression test that failed before the fix.
- [ ] Tests target public behavior, not internals.
- [ ] Refactors done on green with tests rerun.
- [ ] Full suite run at the end (see `naki-verify`).

## Common mistakes

| Mistake | Fix |
|---|---|
| Writing many tests then all the code | one test at a time |
| Test passes on first run | check it can fail: break the code briefly |
| Big leap to a general algorithm | smaller test, smaller step |
| Asserting on mock calls only | assert on the observable result |
| Weakening an assertion to get green | fix the code or explain why the test was wrong |
| Slow tests hitting real services in the loop | fake the boundary, keep integration tests separate |
| Skipping refactor | leave the code cleaner each cycle |
