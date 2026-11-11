---
name: naki-onboarding
description: Get to know an unfamiliar codebase fast: entry points, architecture, data flow, conventions, how to run and test it, then write a short map or CLAUDE.md. Use when joining a repository, opening a project for the first time, or when asked "how is this code organized?".
---

# Codebase Onboarding

Goal: in under an hour, know how to run the project, where the important code lives, and what conventions to follow. Then write it down briefly so the next session does not repeat the work.

## When to use

- First session in a repository.
- Before a large change in an area you have not seen.
- When the user asks for an architecture overview or a CLAUDE.md.

## Core rules

1. Read before guessing. Facts in the map come from files you opened or tool output you saw.
2. Breadth first. Get the shape of the whole repo before reading any single file in depth.
3. Find how it runs and how it is tested early. A project you cannot run is a project you cannot verify.
4. Keep the output short. A map is useful at 60 lines and ignored at 600.
5. Mark uncertainty. "Probably" and "not verified" are fine; invented facts are not.
6. Do not change code while onboarding unless asked.

## Workflow

### 1. Surface scan (5 minutes)

- Top-level listing, ignoring vendored and generated folders.
- README, CONTRIBUTING, existing CLAUDE.md, docs folder, ADRs.
- Manifests: `pyproject.toml`, `requirements*.txt`, `package.json`, `Dockerfile`, `docker-compose.yml`, CI workflows, `Makefile` or task runner files.
- Count files by language to see what the project really is.

```bash
git ls-files | sed 's/.*\.//' | sort | uniq -c | sort -rn | head
git log --oneline -15
git log --since="3 months ago" --name-only --pretty=format: | sort | uniq -c | sort -rn | head -20
```

The last command shows where active work happens.

### 2. Structure from the Code Map

If the `naki-codemap` MCP server is available (build it with `python ~/.claude/naki-kit/tools/codemap.py build <repo>` if needed):

| Step | Tool | What you learn |
|---|---|---|
| Size | `codemap_stats` | files, symbols, edges, languages |
| Core | `codemap_hubs` | the most connected symbols, usually the domain core and shared utilities |
| Detail | `codemap_file` | symbols in a key file without reading all of it |
| Flow | `codemap_path` | how an entry point reaches storage or an external call |

Without the map, use `rg` for definitions and imports, and read the entry points.

### 3. Find the entry points

- Web: app factory, router registration, `main.py`, `app.py`, `server.ts`.
- CLI: `[project.scripts]`, `bin` in `package.json`, `__main__.py`.
- Jobs: schedulers, workers, cron configs, queue consumers.
- Frontend: `main.tsx`, router, top-level layout.

### 4. Trace one real request end to end

Pick the most important user action. Follow it from entry point through validation, business logic, storage and response. Note each file and the data shape at each hop. One full trace teaches more than ten skimmed files.

### 5. Learn the conventions

- Layout: by feature or by layer?
- Error handling style, logging library, config loading.
- Test layout, fixtures, how the DB is handled in tests.
- Formatting and lint tools and their configs.
- Commit message style from `git log`.

### 6. Run it

Find and try (with the user's consent for anything heavy or networked):

- install command
- test command (start with a fast subset)
- lint and type check
- local run

Record what worked and what failed. Follow the project rules skill if the project has one (for example `naki-myapp`) before running anything expensive.

### 7. Write the map

Write to CLAUDE.md only if the user wants it; otherwise give it in chat or a file the user names.

```markdown
# <Project> map

## What it is
One paragraph.

## Run and test
- Install: `...`
- Tests: `...` (fast subset: `...`)
- Lint/types: `...`

## Layout
| Path | Purpose |
|---|---|

## Main flows
- Create alert: api/routes/alerts.py -> services/triage.py -> db/models.py

## Conventions
- ...

## Gotchas
- ...

## Open questions
- ...
```

## Checklist

- [ ] README, manifests, CI read
- [ ] Hubs and sizes known (Code Map or search)
- [ ] Entry points listed
- [ ] One flow traced end to end
- [ ] Run, test and lint commands found and tried
- [ ] Conventions noted
- [ ] Map written, under about 100 lines, uncertain items marked

## Common mistakes

- Reading files alphabetically instead of following execution.
- Copying the README into the map without checking it is still true.
- Treating generated, vendored or archived folders as live code.
- Writing a map so long nobody reads it.
- Missing the second app in a monorepo because the first one looked complete.
- Skipping the test run, then discovering later that half the suite needs a service that is not running.

## Related

- `naki-change-impact` for a specific planned change.
- `naki-adr` for decisions you discover that are not written down.
