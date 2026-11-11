---
name: naki-python-testing
description: Testing Python with pytest, covering test layout, fixtures and scopes, parametrize, mocking only at boundaries, database and async tests, and coverage that measures risk rather than lines. Use when writing or reviewing pytest tests, adding fixtures or mocks, testing code that touches a database or network, or a test suite is slow or flaky.
---

# Python Testing with pytest

## When to use

- Writing tests for new or changed Python code.
- Designing fixtures, conftest structure, or test data factories.
- Deciding what to mock and what to run for real.
- Tests are slow, flaky, or pass while the code is broken.

For the test-first loop see `naki-tdd`; for FastAPI-specific clients see `naki-fastapi`. Follow the project rules skill if the project has one (for example `naki-myapp`), especially for which suites are safe to run locally.

## Core rules

1. **Test behavior, not implementation.** Assert on outputs, state changes and calls across boundaries, not on private helpers or call order inside a unit.
2. **One reason to fail per test.** Name it after the behavior: `test_dedup_merges_alerts_within_window`.
3. **Arrange, act, assert,** visibly separated. Keep setup in fixtures when it repeats.
4. **Mock at the boundary only:** network, clock, randomness, third-party APIs, file system when needed. Do not mock your own classes to test other own classes; that tests the mock.
5. **Use real dependencies when cheap:** an actual Postgres in a container beats a mocked session for repository code.
6. **Tests are independent and order-free.** No shared mutable globals; each test sets up what it needs. Should pass with `pytest -p randomly` or `-x --lf`.
7. **Deterministic:** freeze time, seed randomness, no sleeps waiting for things; poll with a timeout if you must.
8. **Every bug fix ships with a test that failed before the fix.**
9. **Fast by default:** unit tests in milliseconds. Mark slow or external tests (`@pytest.mark.slow`, `@pytest.mark.integration`) and select them explicitly.

## Layout

```text
tests/
  conftest.py          # shared fixtures
  unit/
  integration/
  factories.py         # builders for test objects
pyproject.toml         # [tool.pytest.ini_options]
```

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers --strict-config"
markers = ["integration: needs real services", "slow: takes more than a second"]
asyncio_mode = "auto"
filterwarnings = ["error"]
```

## Fixtures

- Scope: `function` (default) for anything mutable; `session` for expensive immutable setup (DB engine, container).
- Use `yield` fixtures for teardown; teardown runs even when the test fails.
- Prefer factory fixtures over many near-duplicate fixtures.
- Use built-ins: `tmp_path`, `monkeypatch`, `caplog`, `capsys`.

```python
import pytest
from datetime import UTC, datetime

@pytest.fixture
def make_alert():
    def _make(**overrides) -> Alert:
        data = {"source": "ids", "severity": 3, "received_at": datetime(2026, 1, 1, tzinfo=UTC)}
        return Alert(**(data | overrides))
    return _make

def test_high_severity_escalates(make_alert):
    notifier = FakeNotifier()
    escalate(make_alert(severity=5), notifier)
    assert notifier.sent == [("[ids] sev 5", "see console")]
```

A small hand-written fake (`FakeNotifier` with a `sent` list) is often clearer than `MagicMock`.

## Parametrize

```python
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("10.0.0.1", True, id="private-10"),
        pytest.param("192.168.1.5", True, id="private-192"),
        pytest.param("8.8.8.8", False, id="public"),
        pytest.param("not-an-ip", None, id="invalid"),
    ],
)
def test_is_private(raw, expected):
    assert is_private(raw) is expected
```

Use `ids` so failures read clearly. Parametrize edge cases: empty, one, many, boundary values, unicode, `None`.

## Mocking

- Patch where the name is **looked up**, not where it is defined: `mocker.patch("app.services.alerts.httpx.get")` if `alerts.py` does `import httpx`.
- Use `autospec=True` (or `mocker.create_autospec`) so wrong signatures fail.
- For HTTP, prefer `respx` (httpx) or `responses` (requests) over patching the client.
- Freeze time with `time-machine` or `freezegun`, or inject a clock.
- Assert on meaningful calls (`assert_called_once_with(...)`), not on every internal call.

```python
import respx, httpx

@respx.mock
def test_enrich_handles_upstream_503():
    respx.get("https://intel.example/ip/8.8.8.8").mock(return_value=httpx.Response(503))
    with pytest.raises(EnrichmentUnavailable):
        enrich_ip("8.8.8.8")
```

## Database tests

- Run against the same engine as production (Postgres), via a container (`testcontainers`, or a Compose service in CI). SQLite hides differences in types, constraints and locking.
- Apply migrations once per session, then wrap each test in a transaction that rolls back, or truncate tables between tests.
- Never point tests at a shared or production database. Read the URL from a test-only env var and refuse to run if it looks like production.

```python
@pytest.fixture
async def session(engine):
    async with engine.connect() as conn:
        trans = await conn.begin()
        async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint") as s:
            yield s
        await trans.rollback()
```

## Async tests

- `pytest-asyncio` (or `anyio`) with `asyncio_mode = "auto"`; async fixtures work the same way.
- Do not mix event loops between session-scoped async fixtures and function tests without configuring loop scope.

## Coverage that matters

- Run `pytest --cov=src --cov-branch --cov-report=term-missing`.
- Use coverage to **find untested risk** (error branches, permission checks, parsing), not as a target to game.
- Branch coverage over line coverage. A sensible floor (for example 80%) in CI prevents regressions; the important part is which lines are missing.
- A test without a meaningful assertion adds coverage and no safety.

## Workflow

1. List behaviors to verify, including failure paths and edge cases.
2. Write tests from the outside in: public function or endpoint first.
3. Run the single test while iterating: `pytest tests/unit/test_dedup.py::test_merges -x -q`.
4. Run the full relevant suite, then coverage for the touched modules.
5. Check that each new test fails if you break the code it covers.

## Checklist

- [ ] Tests named after behavior; one reason to fail each.
- [ ] Mocks only at external boundaries, autospecced.
- [ ] No sleeps, real clocks or unseeded randomness.
- [ ] DB tests use a real engine and isolate state.
- [ ] Error and edge paths covered, not just the happy path.
- [ ] Suite passes in random order; slow tests marked.

## Common mistakes

- Patching `requests.get` globally when the module imported it under another name.
- Asserting `mock.called` only, which passes for wrong arguments.
- Tests that depend on execution order or on leftover files.
- Using SQLite in tests for Postgres-specific code.
- Catching the exception inside the test instead of `pytest.raises`.
- `assert result` where `result` is a non-empty error object.
- Snapshot tests nobody reviews when they change.
