---
name: naki-git-workflow
description: Git practice covering branching, plain commit messages, PR hygiene, rebase versus merge, conflicts and safe history operations, with hard limits on committing, pushing and hooks. Use when creating branches or commits, preparing a PR, resolving conflicts, or before any command that rewrites or pushes history.
---

# Git Workflow

## When to use

- Before any `git commit`, `git push`, `git rebase`, `git reset`, or branch deletion.
- Preparing a pull request or cleaning up local commits.
- Resolving merge or rebase conflicts.
- Choosing a branching model for a small team.

Follow the project rules skill if the project has one (for example `naki-myapp`); its rules on commits, branches and pushes take precedence over the defaults here.

## Hard rules (always)

1. **Commit only when the user asks.** Finishing a change is not permission to commit. Show the diff summary and wait.
2. **Never force-push without explicit permission** for that specific push. This includes `--force`, `--force-with-lease`, `+refspec`, and deleting remote branches. When permitted, prefer `--force-with-lease`.
3. **Never skip hooks.** No `--no-verify`, no `-c core.hooksPath=...`, no disabling signing. If a hook fails, fix the cause or report it to the user.
4. **Plain commit messages.** No tool or assistant attribution lines, no generated-by footers, no co-author trailers unless the user asks for them.
5. **Do not push unless asked.** Many owners run push and PR commands themselves; offer the exact command instead.
6. **Never rewrite published history** on shared branches (`main`, `develop`, release branches) without explicit permission.
7. **Do not commit secrets, `.env` files, large datasets or build output.** Check `git status` and the staged diff before every commit.
8. **If a guard hook blocks a command with a `kit:` reason,** follow the reason and ask the user. Do not find a workaround.

## Branching

- Default for small teams: **trunk-based with short-lived feature branches.** Branch from up-to-date `main`, keep branches under a few days, merge via PR.
- Name branches by type and topic: `feat/alert-dedup`, `fix/login-timeout`, `chore/bump-ruff`, `docs/adr-0004`.
- If on the default branch when work starts and a commit is requested, create a branch first unless the project rules say otherwise.
- Release branches only when you must support several versions at once.

## Commit messages

```text
Add deduplication window for repeated alerts

Alerts with the same source and signature within 5 minutes are now
merged into one incident instead of opening new ones. The window is
configurable via DEDUP_WINDOW_SECONDS.

Refs #42
```

- Subject: imperative mood, up to about 72 characters, no trailing period. Describe what the commit does.
- Body (optional): why, and anything a reviewer cannot see in the diff. Wrap around 72 characters.
- If the repo uses Conventional Commits (`feat:`, `fix:`), follow it; check `git log --oneline -20` to see the existing style.
- One logical change per commit. Formatting-only changes go in their own commit.

## Before committing

```bash
git status
git diff                 # unstaged
git add -p               # stage hunks deliberately
git diff --staged        # review exactly what goes in
```

- Stage specific files or hunks; avoid `git add -A` in repos with untracked data or local config.
- Run the project's linters and tests first.

## Pull requests

- Small and focused: one feature or fix; a few hundred changed lines at most when possible.
- Title like a commit subject. Description: what changed, why, how it was tested, risks, screenshots for UI.
- Rebase or merge `main` in before requesting review so CI runs against current code.
- Respond to review with new commits; tidy up only if the team squash-merges or asks for it.
- Do not merge with failing checks.

## Rebase vs merge

| Situation | Use |
|---|---|
| Update your own unpublished feature branch | `git rebase origin/main` |
| Update a branch others also push to | `git merge origin/main` |
| Tidy local commits before opening a PR | `git rebase -i` (user runs it; interactive) or `git commit --fixup` plus `git rebase --autosquash` |
| Integrate a PR into main | team's choice: squash merge for a linear history, merge commit to keep branch context |

Rule of thumb: rebase what only you have; merge what others have.

Interactive commands (`git rebase -i`, `git add -i`) need an editor. In non-interactive environments, use `--fixup` and `GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash <base>` or ask the user to run it.

## Resolving conflicts

1. `git status` to list conflicted files.
2. Read both sides and understand each change's intent; check `git log -p --merge <file>` if unclear.
3. Edit to the correct combined result; remove all markers (`<<<<<<<`, `=======`, `>>>>>>>`).
4. Run tests for the affected area.
5. `git add <file>`, then `git rebase --continue` or `git commit` for a merge.
6. If it goes wrong: `git rebase --abort` or `git merge --abort` returns to the start.

Never resolve by blindly taking `--ours` or `--theirs` for whole files unless you know one side is fully obsolete. Lock files: take one side, then regenerate with the package manager.

## Safe history operations

| Goal | Safe command | Avoid |
|---|---|---|
| Undo a pushed commit | `git revert <sha>` | `reset` plus force-push |
| Uncommit locally, keep changes | `git reset --soft HEAD~1` | `reset --hard` |
| Discard local edits to one file | `git restore <file>` (confirm first, it is unrecoverable) | `git checkout .` on everything |
| Stash work in progress | `git stash push -m "wip: dedup"` | committing junk to main |
| Recover a lost commit | `git reflog`, then `git branch rescue <sha>` | panic |
| Remove a committed secret | rotate the secret first, then ask about history rewrite | assuming a new commit fixes it |

- Before any destructive command (`reset --hard`, `clean -fd`, `branch -D`, `push --force`), state what will be lost and get explicit permission. See `naki-safety`.
- Create a backup branch before a risky rebase: `git branch backup/feat-x`.

## Workflow

1. `git status` and `git branch --show-current`; confirm the starting point.
2. Branch from fresh `main` if starting new work.
3. Make changes; run linters and tests.
4. When the user asks to commit: review staged diff, write a plain message, commit.
5. When the user asks for a PR or push: give the command or run it if explicitly asked; never force.

## Checklist

- [ ] User asked for this commit or push.
- [ ] Staged diff reviewed; no secrets, data or build output.
- [ ] Tests and linters pass; hooks ran and passed.
- [ ] Message is plain, imperative, explains why.
- [ ] No force-push, no history rewrite on shared branches without permission.

## Common mistakes

- Committing automatically at the end of a task.
- `git add .` picking up `.env`, notebooks with outputs, or datasets.
- `--no-verify` to get past a failing pre-commit hook.
- Rebasing a branch a teammate already pulled.
- Force-pushing to fix a typo in a commit message on `main`.
- Removing a secret with a new commit and believing it is gone from history.
