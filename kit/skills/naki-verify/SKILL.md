---
name: naki-verify
description: Verification before declaring work done: build, type check, lint, tests, security grep and diff review, ending with an honest PASS/FAIL report that includes failing output. Use when a feature, fix or refactor looks finished, before saying "done", before a commit or pull request, or when the user asks to verify.
---

# Verify before done

"Done" means the checks were run and their results are reported. Never claim success from reading code
alone. Follow the project rules skill if the project has one (for example `naki-myapp`); its commands and
gates override the generic ones below.

## When to use

- At the end of any code change, however small.
- Before proposing a commit or pull request.
- When the user asks "does it work?" or "is it done?".

## Core rules

1. **Run the checks; do not predict them.** If a command was not run, the report says NOT RUN with the reason.
2. **Report failures with their output.** Paste the relevant lines (error message, failing test name,
   file:line), trimmed to what matters. Do not paraphrase a failure into something milder.
3. **Never claim success without evidence.** No "should work", "tests will pass", or "looks good" in place
   of a result.
4. **Use the project's own commands** (from README, `package.json` scripts, `pyproject.toml`, `Makefile`,
   CI config). Do not invent stricter or looser settings.
5. **Do not weaken checks to get green**: no disabling lint rules, skipping tests, lowering coverage gates or
   adding `# type: ignore` without telling the user.
6. **Pre-existing failures are reported separately** from failures your change caused. Check with
   `git stash` or by comparing against the base branch only if it is safe and the user agrees.
7. **Stop at the first blocking failure only if later steps depend on it**; otherwise run all steps and report all.
8. **Guard hook blocks** (messages with a `kit:` reason) are reported as-is; ask the user instead of working
   around them.

## Workflow

### 1. Build

| Stack | Command (typical) |
|---|---|
| Node/Vite | `npm run build` |
| Python package | `python -m build` or import smoke test `python -c "import pkg"` |
| Docker | `docker build -t app:verify .` |

### 2. Types

| Stack | Command |
|---|---|
| TypeScript | `npx tsc --noEmit` |
| Python | `mypy src` or `pyright` (whichever the project uses) |

### 3. Lint and format

| Stack | Command |
|---|---|
| JS/TS | `npm run lint` (eslint), `npx prettier --check .` |
| Python | `ruff check .` and `ruff format --check .` |

### 4. Tests

- Run the focused tests for the change first, then the full suite.
- Python: `pytest -q` (add `--cov` if the project tracks coverage).
- JS/TS: `npx vitest run`; e2e only if the change touches a covered flow: `npx playwright test`.
- Record counts: passed, failed, skipped.

### 5. Security grep

Search the diff, not the whole repo, for new risks:

```bash
git diff --cached --name-only; git diff --name-only
git diff | grep -nEi "(api[_-]?key|secret|password|token)\s*[:=]" 
git diff | grep -nE "(eval\(|exec\(|subprocess\..*shell=True|dangerouslySetInnerHTML|innerHTML\s*=)"
git diff | grep -nE "(console\.log|print\(|debugger|breakpoint\(\))"
```

PowerShell equivalent: `git diff | Select-String -Pattern "password\s*[:=]"`.
Also check that no `.env`, key files, data dumps or large binaries were added.

### 6. Diff review

Read `git diff` (and `git status` for untracked files) top to bottom:

- Every change is intended and related to the task.
- No leftover debug code, commented-out blocks or TODOs you added without saying so.
- New behavior has tests; error paths handled.
- Public interfaces, configs or migrations changed? Call them out.

### 7. Report

Fill in the template below and show it to the user.

## Interpreting results

- A step that cannot run (tool missing, needs a service, needs credentials) is NOT RUN, not PASS.
- Flaky test: rerun once; if it passes, report it as PASS with a note "flaky: failed once, passed on rerun".
- Warnings are not failures, but list new ones your change introduced.
- If anything is FAIL, the overall verdict is FAIL. Offer a fix plan; do not silently start large fixes.

## Common mistakes

| Mistake | Fix |
|---|---|
| "All tests pass" after running one file | state which tests ran |
| Summarizing an error as "minor issue" | paste the error output |
| Marking a skipped step PASS | NOT RUN with reason |
| Fixing lint by disabling the rule | fix the code or ask |
| Reporting only the last command | report every step |
| Committing after verify without being asked | commit only when the user asks |

## Report template

```
VERIFICATION REPORT
Scope: <task / files / branch>
Date: <YYYY-MM-DD>

| Step          | Result              | Command                     | Notes                         |
|---------------|---------------------|-----------------------------|-------------------------------|
| Build         | PASS/FAIL/NOT RUN   | <command>                   |                               |
| Types         | PASS/FAIL/NOT RUN   | <command>                   | <n errors>                    |
| Lint/format   | PASS/FAIL/NOT RUN   | <command>                   | <n issues>                    |
| Tests         | PASS/FAIL/NOT RUN   | <command>                   | <passed>/<failed>/<skipped>   |
| Security grep | PASS/FAIL/NOT RUN   | git diff + patterns         | <findings or none>            |
| Diff review   | PASS/FAIL           | git diff, git status        | <files changed>               |

Failures (output, trimmed):
<step>: <command>
<relevant output lines, file:line, test names>

Pre-existing issues (not caused by this change):
<list or none>

Not run and why:
<list or none>

VERDICT: PASS | FAIL
Next steps: <fix plan or "ready for commit when you ask">
```
