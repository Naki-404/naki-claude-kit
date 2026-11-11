---
name: naki-safety
description: Guarding destructive operations: recursive deletes, force push, hard reset, DROP/TRUNCATE, production data, mass file moves, migrations, and freezing edits to a directory. Use when a command could lose data or history, when touching production or shared systems, before bulk changes, or when the user asks to limit edits to a path.
---

# Safety for destructive operations

Most damage comes from one confident command run in the wrong place. Pause, check scope, prefer the
reversible option, and ask before anything that cannot be undone. Follow the project rules skill if the
project has one (for example `naki-myapp`); its protected paths and rules come first.

## When to use

- Any command that deletes, overwrites, rewrites history or changes shared state.
- Work near production systems, real user data, research datasets or backups.
- Bulk edits, renames or moves across many files.
- The user says "only touch X", "do not edit Y", or "freeze this folder".

## Core rules

1. **Confirm before irreversible actions.** State exactly what will happen (command, target, item count) and
   wait for a clear yes. Approval covers that action only, not similar ones later.
2. **Prefer reversible options:** move to trash or a backup folder instead of delete, `git revert` instead of
   rewriting history, `--force-with-lease` instead of `--force`, a new branch before a risky rebase,
   a transaction with a dry run before a data change.
3. **Check scope first.** Print the target path, list what matches, count it. Never run a delete on a
   variable or glob you have not expanded and inspected.
4. **Dry run when the tool supports it** (`git clean -n`, `rsync --dry-run`, `terraform plan`,
   `SELECT` before `DELETE`, `alembic upgrade --sql`).
5. **Never touch production or real data without an explicit request** naming that environment. Default to
   local or test environments.
6. **Back up before changing data.** Snapshot, dump or copy, and confirm the backup is readable.
7. **Respect guard hook blocks.** A message with a `kit:` reason means stop. Explain the block to the user and
   ask; never rephrase the command, split it, or use another tool to get around it.
8. **Respect freeze scopes** (see below) for the whole session until the user lifts them.
9. **Stop on surprises.** If a count, path or diff differs from what you expected, stop and report.

## Risk table

| Operation | Risk | Safer alternative | Ask first? |
|---|---|---|---|
| `rm -rf <dir>` / `Remove-Item -Recurse -Force` | permanent loss | list contents, move to a backup folder or recycle bin | yes |
| `git push --force` | overwrites others' commits | `git push --force-with-lease`, only on your own branch | yes |
| `git reset --hard` | discards uncommitted work | `git stash`, or `git branch backup-<date>` first | yes |
| `git clean -fdx` | deletes untracked and ignored files (env, data) | `git clean -n` to preview, then targeted delete | yes |
| `git checkout -- .` / `git restore .` | discards edits | `git stash push -m "before restore"` | yes |
| history rewrite (rebase, filter-repo) on shared branches | breaks collaborators | revert commits instead | yes |
| `DROP TABLE` / `DROP DATABASE` | permanent loss | rename table, keep backup, drop later | yes |
| `TRUNCATE` / `DELETE` without `WHERE` | mass loss | `SELECT count(*)` with the same filter, run in a transaction | yes |
| `UPDATE` across many rows | silent corruption | transaction, check affected count, then commit | yes |
| schema migration on prod | downtime, data loss | test on a copy, expand-contract, reviewed downgrade path | yes |
| mass move/rename (`mv`, scripts, codemods) | broken imports, lost files | dry-run list, do it in git with a clean tree, one commit | yes if outside the task |
| overwriting a file you did not read | lost content | read first, edit in place | yes if user-owned |
| `chmod -R`, `icacls /T`, ownership changes | broken access | narrow the path | yes |
| deleting cloud resources, buckets, volumes | permanent loss, cost | snapshot, disable before delete | yes |

## Workflow for a destructive step

1. **Name it.** Write the exact command and why it is needed.
2. **Inspect the target.** Examples:
   - `ls -la path/` or `Get-ChildItem path -Recurse | Measure-Object`
   - `git status`, `git log --oneline -5`, `git branch -vv`
   - `SELECT count(*) FROM alerts WHERE created_at < '2025-01-01';`
3. **Make it reversible** where possible: backup, stash, branch, transaction.
4. **Ask the user** with the details: "This will delete 412 files under `build/cache` (1.3 GB). A copy is not
   kept. Proceed?"
5. **Run it once, narrowly.** No chained destructive commands with `&&` after a risky step.
6. **Verify the result** (count again, `git status`, row count) and report what changed.

## Examples

Safer SQL change:

```sql
BEGIN;
SELECT count(*) FROM alerts WHERE status = 'stale' AND updated_at < now() - interval '90 days';
DELETE FROM alerts WHERE status = 'stale' AND updated_at < now() - interval '90 days';
-- compare the DELETE row count with the SELECT, then:
COMMIT;   -- or ROLLBACK;
```

Safer git cleanup:

```bash
git branch backup/before-cleanup
git stash push -u -m "wip before cleanup"
git clean -n -d          # preview only
```

Safer delete in PowerShell:

```powershell
Get-ChildItem .\tmp\exports -File | Select-Object FullName, Length
Move-Item .\tmp\exports .\_trash\exports_2026-11-08   # instead of Remove-Item -Recurse
```

## Freeze scopes

When the user asks to freeze a directory ("do not edit `data/`", "only change files in `src/ui`"):

1. Restate the scope: frozen paths, or the single allowed path.
2. Before every Edit, Write, move, delete or generated output, check the target path against the scope.
   Generated files (formatters, codemods, build outputs) count too.
3. Reading frozen files is fine unless the user says otherwise.
4. If the task needs a change in a frozen area, stop and ask; describe the exact change you would make.
5. Keep the freeze until the user lifts it explicitly. Mention it in the final report.
6. If the kit's `kit_verify_frozen` tool is available, use it to confirm frozen paths are unchanged.

## Checklist

- [ ] Target path, branch, database and environment printed and checked.
- [ ] Count of affected items known and expected.
- [ ] Dry run done where available.
- [ ] Backup, stash, branch or transaction in place.
- [ ] User confirmed this specific irreversible action.
- [ ] Freeze scope respected; no edits in frozen paths.
- [ ] Result verified and reported.

## Common mistakes

| Mistake | Fix |
|---|---|
| `rm -rf $DIR/` with `DIR` empty | quote variables, check they are set, list first |
| Force push to `main` to "fix" a mistake | `git revert`, or ask the owner |
| `reset --hard` to clean up, losing the user's edits | `git stash` first |
| Running a migration against the wrong `DATABASE_URL` | print the target host/db before running |
| Treating one approval as permission for the next delete | ask again |
| Working around a `kit:` block with a different command | stop and ask the user |
