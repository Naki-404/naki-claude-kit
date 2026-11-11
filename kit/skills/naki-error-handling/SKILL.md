---
name: naki-error-handling
description: Designing how code fails, covering an error taxonomy, retries with backoff and jitter, timeouts, circuit breakers, user-facing messages and logging errors. Use when adding network or service calls, designing exception types, deciding what to retry, writing error responses, or reviewing code that swallows failures.
---

# Error Handling

## When to use

- Any call that crosses a process boundary: HTTP, database, queue, file system, LLM API.
- Designing exception classes or error codes for a module or service.
- A failure was silent, or an outage cascaded through retries.
- Writing messages that users or operators will read.

Examples are in Python; the rules apply to any language. See `naki-api-design` for HTTP error bodies and `naki-python` for general Python style.

## Error taxonomy

Classify every failure before deciding what to do with it.

| Class | Examples | Action |
|---|---|---|
| Validation / client | bad input, missing field, forbidden | do not retry; return a clear message (4xx) |
| Not found / conflict | missing row, duplicate key, stale version | do not retry blindly; return 404/409 or re-read |
| Transient | timeout, connection reset, 429, 502, 503, 504, deadlock, serialization failure | retry with backoff, bounded |
| Resource exhausted | disk full, pool exhausted, quota | back off, alert, shed load |
| Programmer bug | `KeyError`, `TypeError`, assertion | do not retry; fail loudly, log traceback, fix code |
| Unknown | anything else | treat as non-retryable bug until classified |

## Core rules

1. **Never swallow an error silently.** Every `except` either handles the case fully, adds context and re-raises, or logs with traceback at a boundary. `except: pass` is a bug.
2. **Catch narrowly, as close as you can act.** Catch the specific exception where you know how to recover; let the rest propagate to a top-level boundary (request handler, job runner, CLI `main`).
3. **Add context when re-raising:** `raise FetchError(f"fetch {url}") from exc`. Keep the original as `__cause__`.
4. **Every remote call has a timeout.** Connect and read timeouts both. No default infinite waits.
5. **Retry only transient errors, only idempotent operations,** with exponential backoff, full jitter, a max attempt count and a total deadline. Honor `Retry-After`.
6. **Retry in one layer only.** If the HTTP client, the service and the job runner all retry 3 times, one failure becomes 27 calls.
7. **Fail fast on dependencies that are down** with a circuit breaker, so threads are not tied up waiting on a dead service.
8. **No silent fallbacks to fake data.** A fallback (cache, default) must be explicit, logged and visible in metrics. Returning an empty list when the DB is down hides an outage.
9. **Separate user messages from diagnostics.** Users get a short, actionable message and a reference id. Logs get the exception, inputs (redacted), and ids.
10. **Log an error once,** at the boundary that handles it. Logging and re-raising at every layer floods logs with duplicates.
11. **Clean up in `finally` or context managers,** not in the happy path only.

## Retry with backoff

```python
import random, time
from collections.abc import Callable

class TransientError(Exception):
    pass

def retry[T](fn: Callable[[], T], *, attempts: int = 4, base: float = 0.5,
             cap: float = 8.0, deadline: float = 20.0) -> T:
    start = time.monotonic()
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except TransientError:
            elapsed = time.monotonic() - start
            if attempt == attempts or elapsed >= deadline:
                raise
            delay = random.uniform(0, min(cap, base * 2 ** attempt))
            time.sleep(min(delay, deadline - elapsed))
    raise AssertionError("unreachable")
```

Libraries such as `tenacity` (Python) do the same; configure them with the same limits. Map library exceptions (`httpx.TimeoutException`, HTTP 503) to your transient class in one place.

## Timeouts

```python
import httpx

client = httpx.Client(timeout=httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=3.0))
```

- Budget timeouts top-down: if the caller's request has 15 s, downstream calls must fit inside it, retries included.
- For async code, `asyncio.timeout(5)` around the awaited block.
- Database: set `statement_timeout` for app roles.

## Circuit breaker

States: **closed** (calls pass, failures counted), **open** (calls fail immediately for a cool-down period), **half-open** (a few trial calls; success closes, failure reopens).

```python
class CircuitOpen(Exception):
    pass

class Breaker:
    def __init__(self, threshold: int = 5, cooldown: float = 30.0) -> None:
        self.threshold, self.cooldown = threshold, cooldown
        self.failures, self.opened_at = 0, 0.0

    def call[T](self, fn: Callable[[], T]) -> T:
        if self.failures >= self.threshold:
            if time.monotonic() - self.opened_at < self.cooldown:
                raise CircuitOpen("dependency unavailable")
            self.failures = self.threshold - 1  # half-open: one trial
        try:
            result = fn()
        except TransientError:
            self.failures += 1
            if self.failures >= self.threshold:
                self.opened_at = time.monotonic()
            raise
        self.failures = 0
        return result
```

Use one breaker per dependency, shared across requests; expose its state in metrics. This sketch is not thread safe; add a lock or use a library in concurrent code.

## Error types for a module

```python
class TriageError(Exception):
    """Base for this package; callers can catch one type."""
    code = "triage_error"

class InvalidAlert(TriageError):
    code = "invalid_alert"

class EnrichmentUnavailable(TriageError):
    code = "enrichment_unavailable"
```

- One base exception per package, specific subclasses with a stable `code`.
- Map them to transport errors (HTTP status, CLI exit code) at the boundary, not inside the domain.

## User-facing messages

- Say what happened and what the user can do: "The file is larger than 20 MB. Upload a smaller file."
- Do not blame the user, do not expose internals ("NullReferenceException", SQL, file paths, stack traces).
- Include a reference id that matches the log line, so support can find it.
- Same message for "wrong user" and "wrong password" on login.

## Logging errors

- Use `logger.exception("enrich failed alert_id=%s", alert_id)` inside `except` to include the traceback.
- Structured fields: request id, user or tenant id, operation, dependency, attempt number, duration.
- Redact secrets, tokens, passwords and personal data before logging.
- Level: `warning` for handled transient failures that recovered, `error` for failed operations, `critical` for process-level failure.

## Workflow

1. List every external call and failure point in the change.
2. Classify each failure with the taxonomy.
3. Add timeouts everywhere; add retries only for transient plus idempotent cases, in one layer.
4. Define exception types and the boundary that maps them to responses or exit codes.
5. Write tests that force each failure (timeout, 503, invalid input) and assert the behavior.

## Checklist

- [ ] No bare or empty `except`; no silent fallback.
- [ ] Timeouts on every remote call.
- [ ] Retries bounded, jittered, only for transient and idempotent work, in one layer.
- [ ] Circuit breaker or fast-fail for flaky critical dependencies.
- [ ] Errors chained with context; logged once with traceback.
- [ ] User messages actionable, free of internals, with a reference id.
- [ ] Failure paths covered by tests.

## Common mistakes

- Retrying a non-idempotent POST and charging a customer twice.
- Retrying on 400 or 401.
- Fixed delay retries from many clients at once (thundering herd); add jitter.
- `except Exception as e: return None` turning a bug into a wrong answer.
- Logging `str(e)` without the traceback.
- Showing raw exception text in the UI.
