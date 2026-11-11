---
description: Safe dead-code removal and cleanup in small steps, with tests after each step
argument-hint: [path or scope]
---

# /naki-refactor

Remove dead code, unused dependencies and duplication without changing behavior. Small steps, each verified.

## 1. Scope

- Scope: the path in `$ARGUMENTS`, otherwise ask the user which package or directory to clean.
- Read the project rules skill if present (for example `naki-myapp`). Never touch frozen directories, data, research
  outputs or migrations. If a guard hook blocks an action with a `kit:` reason, follow it and ask the user.

## 2. Baseline

Run the project's tests, linters and type checks for the scope. If anything fails, report it and stop: cleanup on a
red baseline cannot be proven safe.

## 3. Analyze and clean

Run the `naki-refactor-cleaner` agent on the scope. It will:
1. Find candidates (unused imports, functions, files, exports, dependencies, feature flags, duplicates) with tools
   such as `ruff`, `vulture`, `knip` and with `codemap_symbol` caller counts when a Code Map exists.
2. Confirm each candidate by searching for dynamic and external use (entry points, routes, string imports, config,
   templates, other repos).
3. Classify as safe, careful or risky.
4. Remove safe items in small batches, running tests after each batch and reverting any batch that breaks.

## 4. Ask before risky items

Present careful and risky candidates with evidence and let the user choose. Public APIs, anything possibly used by
other repos and anything referenced by string go here.

## 5. Final verification

Run the project's full test suite, linters, type check and build. Use the `naki-verify` checklist.

## 6. Report

```
## Refactor report
Scope: ...
Removed:
- <item> (<file>): <evidence it was unused>
Merged duplicates: ...
Kept (uncertain or risky): ...
Checks: tests <result>, lint <result>, types <result>, build <result>
Net lines removed: <N>
```

Commit only when the user asks. Suggest one commit per logical cleanup so each can be reverted alone.
