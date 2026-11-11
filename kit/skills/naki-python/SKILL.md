---
name: naki-python
description: Idiomatic modern Python 3.12 for production code, covering type hints, dataclasses and pydantic models, exceptions, packaging with pyproject.toml, and performance basics. Use when writing, refactoring or reviewing Python modules, choosing data containers, setting up a package, or chasing a slow loop.
---

# Modern Python

## When to use

- Writing or reviewing any Python 3.11+ code (target 3.12 unless the project pins otherwise).
- Deciding between dict, dataclass, NamedTuple, TypedDict and pydantic model.
- Setting up `pyproject.toml`, linters, type checking, or a src layout.
- A script is slow or memory heavy and you need a first pass before profiling deeper.

Follow the project rules skill if the project has one (for example `naki-myapp`). For FastAPI specifics see `naki-fastapi`, for tests see `naki-python-testing`, for failure design see `naki-error-handling`.

## Core rules

1. **Type every public function.** Parameters and return types on anything imported elsewhere. Use built-in generics (`list[str]`, `dict[str, int]`), `X | None` instead of `Optional[X]`, and `type` aliases (3.12 `type UserId = int`).
2. **Pick the lightest container that holds the invariant.**
   | Need | Use |
   |---|---|
   | Internal record, no validation | `@dataclass(slots=True, frozen=True)` |
   | Untrusted input (HTTP, files, env) | pydantic `BaseModel` |
   | Shape of an existing dict (JSON passthrough) | `TypedDict` |
   | Small fixed tuple with names | `NamedTuple` |
   | Closed set of values | `enum.StrEnum` / `Enum` |
3. **Validate at the edge, trust inside.** Parse raw input into typed objects once; core code takes typed objects, not dicts.
4. **No mutable default arguments.** Use `None` and create inside, or `field(default_factory=list)` in dataclasses.
5. **Raise specific exceptions, catch narrowly.** Never bare `except:`; `except Exception` only at process or request boundaries, and then log with traceback. Chain with `raise NewError(...) from exc`.
6. **Use context managers for resources.** Files, locks, DB sessions, temp dirs. Write your own with `contextlib.contextmanager` when setup and teardown pair up.
7. **Paths are `pathlib.Path`.** No string concatenation of paths; always pass `encoding="utf-8"` when reading or writing text (Windows defaults differ).
8. **Logging, not print,** in library and service code. `logger = logging.getLogger(__name__)` at module level; use lazy formatting `logger.info("loaded %d rows", n)`.
9. **Keep modules import-safe.** No side effects at import time beyond constants; put script entry under `if __name__ == "__main__":` or a `main()` exposed via `[project.scripts]`.
10. **Prefer composition and plain functions** over deep class hierarchies. Use `typing.Protocol` for structural interfaces.

## Workflow

1. Read the existing style: `pyproject.toml`, ruff and mypy/pyright settings, Python version.
2. Model the data first (dataclasses or pydantic), then write functions over it.
3. Write the code with types; keep functions short and pure where possible.
4. Run `ruff check --fix`, `ruff format`, then the type checker (`mypy` or `pyright`), then tests.
5. Profile before optimizing (`python -m cProfile -s cumtime script.py`, or `py-spy` for running processes).

## Packaging baseline

```toml
[project]
name = "triage-core"
requires-python = ">=3.12"
dependencies = ["pydantic>=2.7", "httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest", "ruff", "mypy"]

[project.scripts]
triage = "triage_core.cli:main"

[tool.ruff]
line-length = 100
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]

[tool.mypy]
strict = true
```

- Use a `src/` layout so tests run against the installed package, not the working directory.
- Pin direct dependencies with lower bounds in `pyproject.toml`; lock exact versions in a lock file (`uv lock`, `pip-tools`) for apps.
- On Windows, activate venvs with `.venv\Scripts\Activate.ps1` (PowerShell) or `source .venv/Scripts/activate` (Git Bash).

## Examples

Dataclass for internal state, pydantic at the boundary:

```python
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel, Field

class AlertIn(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    severity: int = Field(ge=1, le=5)
    raw: str

@dataclass(slots=True)
class Alert:
    source: str
    severity: int
    received_at: datetime
    tags: list[str] = field(default_factory=list)

def to_domain(payload: AlertIn, now: datetime) -> Alert:
    return Alert(payload.source, payload.severity, now)
```

Protocol instead of inheritance:

```python
from typing import Protocol

class Notifier(Protocol):
    def send(self, subject: str, body: str) -> None: ...

def escalate(alert: Alert, notifier: Notifier) -> None:
    if alert.severity >= 4:
        notifier.send(f"[{alert.source}] sev {alert.severity}", "see console")
```

Exception chaining with context:

```python
import tomllib
from pathlib import Path

class ConfigError(Exception):
    pass

def load_config(path: Path) -> dict[str, object]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot load {path}") from exc
```

## Performance basics

- Choose the right structure first: `set`/`dict` membership is O(1), `list` is O(n).
- Build strings with `"".join(parts)`, not `+=` in a loop.
- Use generators for large streams (`for line in f:`), not `f.readlines()`.
- `functools.cache` for pure, hashable-argument functions; watch memory.
- Vectorize numeric work with numpy or polars instead of Python loops.
- CPU-bound parallelism: `concurrent.futures.ProcessPoolExecutor`. I/O-bound: `asyncio` or threads.
- Do not micro-optimize without a profile showing the hotspot.

## Checklist

- [ ] Public functions fully typed; type checker passes.
- [ ] Untrusted input parsed into a pydantic model or validated explicitly.
- [ ] No mutable defaults, no bare `except`, no swallowed exceptions.
- [ ] Files opened with `with` and explicit `encoding`.
- [ ] No secrets or absolute user paths hardcoded.
- [ ] `ruff check` and `ruff format --check` clean.
- [ ] New behavior covered by tests.

## Common mistakes

- `def f(items=[])`: the list is shared across calls.
- `except Exception: pass` hiding real failures; at minimum log and re-raise.
- Comparing to `None` with `==`; use `is None`.
- Using `datetime.now()` without a timezone; prefer `datetime.now(UTC)` and store UTC.
- Catching `KeyError` around a large block instead of using `dict.get` on the one lookup.
- Returning different types from one function (`str` or `False`); return `str | None` or raise.
- Circular imports from putting everything in `__init__.py`; keep it thin.
- `from module import *` in non-trivial code.
