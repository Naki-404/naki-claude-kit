---
description: Checklist review of local uncommitted changes or a given PR; findings by severity with file:line and fixes
argument-hint: [PR number or URL]
---

# /naki-review

Review code with a fixed checklist. This is a single-pass review; for a multi-agent pass use `/naki-review-pr`.
Do not edit files in this command.

## 1. Collect the change

- No argument: local mode. Use `git status --porcelain`, `git diff HEAD` and read untracked files.
- PR number or URL in `$ARGUMENTS`: PR mode. Use `gh pr view <pr> --json title,body,files` and `gh pr diff <pr>`.
- If there is nothing to review, say so and stop.

Read the project rules skill if present (for example `naki-myapp`). Its rules are part of the checklist.

## 2. Read context

For each changed hunk, read the whole function, its callers and its tests. If a Code Map exists,
`codemap_symbol` gives callers quickly.

## 3. Checklist

Correctness
- [ ] Logic matches intent; edge cases (empty, null, boundary, unicode, time zones) handled
- [ ] No partial writes on failure; transactions where needed
- [ ] Concurrency and ordering safe

Errors (`naki-error-handling`)
- [ ] No swallowed exceptions or silent fallbacks
- [ ] Timeouts on external calls; retries bounded

Security (`naki-sec-web-appsec`)
- [ ] No secrets in code or config
- [ ] Input validated at boundaries; queries parameterized
- [ ] Authorization checked for every object access

Interfaces
- [ ] API, schema and config changes backward compatible or flagged
- [ ] Migrations reversible and safe (`naki-postgres`)

Tests
- [ ] New behavior and failure paths tested
- [ ] Tests would fail if the change were reverted

Clarity
- [ ] Names and structure readable; no dead code or debug leftovers

## 4. Run cheap checks

Run the project's linters and the tests for touched modules if safe (no network, paid APIs or production data).

## 5. Report

```
## Review: <local changes | PR #N title>
Verdict: Approve | Approve with comments | Request changes

### [Critical|High|Medium|Low] <title>
- Location: file:line
- Problem: ...
- Failure scenario: ...
- Suggested fix: ...

Checks run: <commands and results>
Checklist items with no issues: ...
```

Rank findings by severity. If nothing significant was found, say "No issues found" plainly and list what was
checked. Do not post comments to GitHub unless the user asks.
