---
name: naki-search-first
description: Look for existing code, standard library features, maintained packages and tools before writing new code, then evaluate any candidate dependency for fit, health, license and security. Use when starting a feature, writing a utility, adding a dependency or integration, or when something feels like a solved problem.
---

# Search First

Most code you are about to write already exists somewhere: in this repository, in the standard library, or in a well-maintained package. Finding it is cheaper than writing, testing and maintaining a new copy.

## When to use

- Before writing a helper (date parsing, retries, slugify, CSV handling, rate limiting).
- Before adding a dependency.
- Before building an integration with an external service.
- When you notice you are about to write the same thing twice.

## Core rules

1. Search in this order: this repository, the standard library, already installed dependencies, then new packages.
2. Prefer reusing over duplicating, and extending over forking.
3. A new dependency is a long-term commitment. Evaluate it before adding it.
4. Small, stable logic (under about 30 lines, no edge-case minefield) is often better written than imported.
5. Never add a dependency silently. Tell the user what, why and the alternatives.
6. Follow the project rules skill if the project has one (for example `naki-myapp`), which may restrict new dependencies or network installs.

## Workflow

### 1. State the need precisely

"Parse ISO 8601 timestamps with offsets into aware datetimes" is searchable. "Handle dates" is not.

### 2. Search the repository

```bash
rg -n "def .*retry|backoff" --type py
rg -n "fromisoformat|parse_datetime|dateutil" --type py
rg -ln "slugify" .
```

If the `naki-codemap` MCP server is available, `codemap_search` finds symbols by words in their names, and `codemap_symbol` shows how an existing helper is used. Look in `utils`, `common`, `core`, `shared` and `lib` folders.

### 3. Check the standard library and existing dependencies

Python examples that people often reimplement:

| Need | Already there |
|---|---|
| ISO datetimes | `datetime.fromisoformat` (3.11+ handles most forms) |
| Caching | `functools.cache`, `functools.lru_cache` |
| Paths | `pathlib` |
| Data containers | `dataclasses`, `typing.NamedTuple` |
| Grouping and windows | `itertools.groupby`, `itertools.batched` (3.12) |
| Temp files | `tempfile` |
| Retry with backoff | check if `tenacity` or an HTTP client retry option is already installed |

Look at the lock file or `pip list` / `npm ls` before proposing anything new.

### 4. Search for packages and tools

- PyPI, npm, or the language registry, by function rather than by name.
- Framework built-ins first (FastAPI dependencies, SQLAlchemy events, React hooks).
- For an external service: its official SDK, then a maintained community client.
- For Claude Code workflows: existing naki skills, agents and MCP tools in the kit.

### 5. Evaluate candidates

| Criterion | Check |
|---|---|
| Fit | Does it solve the exact need without large unused surface? |
| Maintenance | Release in the last year, issues answered, more than one maintainer |
| Adoption | Download counts, used by known projects |
| Quality | Typed, tested, documented, sane API |
| Size | Transitive dependencies, install size, native build steps (painful on Windows) |
| License | Compatible with the project (MIT, BSD, Apache-2.0 are usually safe; check GPL/AGPL) |
| Security | Known advisories (`pip-audit`, `npm audit`), typosquat risk: verify the exact name |
| Exit cost | How hard to replace if it dies? Wrap it behind a small interface if central |

### 6. Decide: adopt, extend, or build

- Adopt: a candidate fits well and passes evaluation.
- Extend: an existing in-repo helper almost fits; add a parameter or case with a test.
- Build: nothing fits, or the logic is small and stable, or dependencies are restricted. Write it with tests and a short docstring stating why it is custom.

### 7. Report the decision

```markdown
Need: parse ISO 8601 with offsets
Found: utils/time.py:parse_ts (handles Z only), datetime.fromisoformat (3.12, handles offsets)
Decision: extend parse_ts to use fromisoformat; no new dependency
```

## Checklist

- [ ] Need stated precisely
- [ ] Repository searched (text and Code Map)
- [ ] Standard library and installed packages checked
- [ ] Candidates evaluated on fit, maintenance, license, security, size
- [ ] Decision and reason reported to the user
- [ ] New dependency pinned in the manifest and lock file, with user approval

## Common mistakes

- Writing a third retry helper next to two existing ones.
- Pulling a large framework for one function.
- Installing a package whose name is one letter off from the real one.
- Picking the first search result without checking its last release date.
- Copying code from a forum answer without understanding or testing it, and without checking its license.
- Building custom when the framework already has the feature behind a setting.
