---
description: Multi-agent PR review: code, security, failure-hunting and language reviewers in parallel, one merged report
argument-hint: [PR number or URL, or branch; default current branch vs main]
---

# /naki-review-pr

Review a pull request with several reviewer agents in parallel and merge their results into one report without
duplicates. Do not edit files in this command.

## 1. Collect the change

- PR number or URL in `$ARGUMENTS`: `gh pr view <pr> --json number,title,body,baseRefName,headRefName,files` and
  `gh pr diff <pr>`.
- Branch name: `git diff <base>...<branch>`, base defaults to `main` (or `master` if `main` is missing).
- No argument: current branch against its base.
- List changed files and classify them: Python, TypeScript/React, SQL/migrations, ML training/eval, config, docs.

Read the project rules skill if present (for example `naki-myapp`) and pass its key rules to every agent.

## 2. Pick the reviewers

Always:
- `naki-code-reviewer`
- `naki-security-reviewer`
- `naki-failure-hunter`

Plus the matching language or domain reviewer for each file group present:
- Python or FastAPI files: `naki-python-reviewer`
- `.ts`, `.tsx`, `.js`, `.jsx`: `naki-frontend-reviewer`
- models, SQL, Alembic migrations: `naki-database-reviewer`
- training, evaluation or dataset code: `naki-ml-reviewer`

## 3. Run them in parallel

Launch all selected agents in one message so they run concurrently. Give each one:
- the PR title, description and base/head refs,
- the list of files relevant to it,
- the instruction to report findings with severity, file:line, failure scenario and suggested fix, and to say
  plainly if it found nothing.

## 4. Merge

1. Collect all findings.
2. Deduplicate: findings on the same file and nearby lines with the same root cause become one entry. Keep the
   highest severity and the clearest fix, and list which agents raised it.
3. When agents disagree on severity, use the higher one and note the disagreement.
4. Drop findings that are pure lint style already enforced by project tools.
5. Sort by severity, then by file.

## 5. Report

```
## PR review: #<N> <title>
Reviewers: <agents run>
Verdict: Approve | Approve with comments | Request changes

### Critical
- [file:line] <title> (raised by: ...)
  Problem / scenario / fix
### High
### Medium
### Low

### Tests
<missing tests, test results the agents reported>

### Reviewers with no findings
- <agent>: <what it checked>
```

If no agent found anything significant, say so plainly. Do not post comments to GitHub, approve or merge unless the
user asks.
