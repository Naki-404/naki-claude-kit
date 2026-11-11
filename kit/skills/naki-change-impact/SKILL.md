---
name: naki-change-impact
description: Impact analysis before a risky change (callers, data, contracts, tests, deploy, rollback) and a comparison of the planned impact with the actual diff afterwards. Use when changing shared code, public interfaces, schemas, auth, config or anything with an unclear blast radius.
---

# Change Impact Analysis

Know what a change touches before you make it, then check that the diff touched only that.

## When to use

- Editing a function, class or module that other code imports or calls.
- Changing a public API, CLI flag, file format, event payload or config key.
- Database schema or data migrations.
- Authentication, authorization, secrets, logging of sensitive data.
- Renames, moves, signature changes, dependency upgrades.
- Any time someone asks "what will this break?"

Skip it for local, private edits with one caller and good tests. A typo fix does not need a report.

## Core rules

1. Evidence over memory. Every claimed caller, consumer or test comes from a search or a tool result, not a guess.
2. Find callers before editing, not after the tests fail.
3. Separate direct impact (code that calls the changed thing) from indirect impact (code that depends on its behavior or data).
4. Name the rollback before you start. If there is no clean rollback, say so and ask the user.
5. After implementing, compare the plan with the real diff. Unplanned files in the diff need an explanation.
6. Follow the project rules skill if the project has one (for example `naki-myapp`), especially for frozen data, migrations and shared configs.

## Workflow

### 1. Describe the change in one sentence

"Rename `score_alert(alert)` to `score_alert(alert, *, policy)` and make `policy` required." If you cannot write this sentence, the change is not ready.

### 2. Find direct dependents

If the Code Map MCP server (`naki-codemap`) is available, use it first:

| Question | Tool |
|---|---|
| Where is the symbol and who calls it? | `codemap_symbol` |
| What sits one hop around it (callers, callees, imports)? | `codemap_neighbors` |
| Does module A reach B, and through what? | `codemap_path` |
| I only know words, not the name | `codemap_search` |

If the map is stale or missing, rebuild it (`python ~/.claude/naki-kit/tools/codemap.py build <repo>`) or fall back to text search. The map misses dynamic calls, so always add a text search:

```bash
rg -n "score_alert" --type py
rg -n "score_alert" -g "*.{ts,tsx,js,json,yaml,yml,md,sql}"
```

Search strings too: route names, config keys, env var names, column names, event names, and serialized field names often appear only as literals.

### 3. Walk the impact areas

| Area | Questions |
|---|---|
| Call paths | Which callers break? Which change behavior silently? |
| Data and schema | Does stored data change shape? Old rows, old files, caches? |
| Contracts | API responses, CLI output, file formats, message payloads used by other services or users? |
| Tests | Which tests cover this? Which will need updates? Is anything uncovered? |
| Config and env | New or renamed keys? Defaults? Docs for operators? |
| Security | Does it change who can do what, or what gets logged? |
| Docs and ADRs | Does it contradict a recorded decision (see `naki-adr`)? |
| Deploy | Order of rollout (DB before app?), feature flag, downtime? |
| Rollback | Revert commit only, or data rollback too? Is it reversible? |

### 4. Rate the risk

- Low: private code, all callers in the same module, good tests.
- Medium: several modules, behavior change visible to users, tests partial.
- High: public contract, schema, auth, data loss possible, or no rollback.

High risk means: write the plan down, get user approval, and prefer an expand then contract approach (add the new path, migrate callers, remove the old path later).

### 5. Write the pre-change report

```markdown
## Impact: make policy required in score_alert
Risk: medium
Direct: triage/service.py (2 calls), api/routes/alerts.py (1), jobs/rescore.py (1)
Indirect: rescore job output format unchanged; API response unchanged
Tests: tests/test_triage.py covers service; jobs/rescore.py has no test (add one)
Config: none
Deploy: single release, no migration
Rollback: revert commit
Planned files: the 4 above + 2 test files
```

### 6. Implement, then compare with the diff

```bash
git diff --stat
git diff --name-only
```

For each file in the diff: was it planned? For each planned file: is it in the diff? Then run the project's tests and linters (see `naki-verify`).

```markdown
## Post-change check
Planned and changed: 4/4
Unplanned changes: utils/policy.py (added default factory, needed by job)
Planned but unchanged: none
Tests: 212 passed; new test for rescore job added
Residual risk: callers outside this repo (none known)
```

## Checklist

- [ ] Change described in one sentence
- [ ] Callers found with Code Map and text search
- [ ] String literals (routes, keys, columns) searched
- [ ] Data, contracts, config, security, deploy considered
- [ ] Risk rated; high risk approved by the user
- [ ] Rollback named
- [ ] Diff compared with plan; surprises explained
- [ ] Tests and linters run

## Common mistakes

- Trusting the call graph alone. Reflection, dependency injection, string dispatch, templates and SQL are invisible to it.
- Forgetting consumers outside the repo: dashboards, scripts, other services, saved notebooks.
- Treating "tests pass" as "nothing broke" when the changed code has no tests.
- Bundling an unrelated refactor into a risky change, which makes the diff impossible to compare with the plan.
- Changing a shared default value. It changes behavior for every caller that did not pass the argument.
- Working around a guard hook block. If a hook stops an edit with a `kit:` reason, follow the reason and ask the user.
