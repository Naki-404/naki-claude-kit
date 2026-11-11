---
description: Run the verification checklist (build, types, lint, tests, security grep, diff review) and print a PASS/FAIL report
argument-hint: [quick | full]
---

# /naki-verify

Verify the current work before declaring it done, following `naki-verify`. Report what actually ran; never claim a
check passed if it did not run.

`quick` runs phases 1 to 4 on touched modules only. `full` (default) runs everything.

Read the project rules skill if present (for example `naki-myapp`). It may define the exact commands and forbid some
tests (paid APIs, GPU, real data). Follow it. If a guard hook blocks a command with a `kit:` reason, record it as
BLOCKED and ask the user.

## Phases

1. **Build**: the project build command (`npm run build`, `python -m build` or the documented one). Skip with a note
   if the project has no build step.
2. **Types**: `mypy` / `pyright`, `npx tsc --noEmit`, whichever the project configures.
3. **Lint**: `ruff check .` and `ruff format --check .`, `npx eslint .`, or the project's lint script.
4. **Tests**: the project's test command with coverage when configured. Record passed, failed, skipped.
5. **Security grep** on the diff (`git diff HEAD` plus untracked files):
   - secrets: private keys, `api_key=`, `password=`, tokens, connection strings with credentials
   - debug leftovers: `print(` / `console.log` in production code, `breakpoint()`, `debugger`
   - risky calls: `eval`, `exec`, `shell=True`, `pickle.loads`, `yaml.load(` without safe loader,
     `dangerouslySetInnerHTML`
6. **Diff review**: read the full diff. Check for unintended files, large generated files, commented-out code, TODOs
   added without a ticket, and changes outside the task scope.

If `kit_verify_frozen` is available and the project uses frozen data, run it and include the result.

## Rules

- Run phases in order; continue after a failure so the report is complete.
- Do not fix anything in this command. List failures and suggest `/naki-build-fix` or a specific change.
- Keep command output in the report short: counts and the first relevant errors.

## Report

```
## Verification report
Mode: quick | full
| Phase | Command | Result | Notes |
|---|---|---|---|
| Build | ... | PASS/FAIL/SKIP/BLOCKED | ... |
| Types | ... | ... | ... |
| Lint | ... | ... | ... |
| Tests | ... | ... | N passed, N failed, coverage N% |
| Security grep | ... | ... | ... |
| Diff review | ... | ... | ... |

Overall: PASS | FAIL
Must fix before done:
1. ...
```

Overall is PASS only if no phase is FAIL or BLOCKED.
