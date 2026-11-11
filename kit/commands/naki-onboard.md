---
description: Map an unfamiliar repository and write a short onboarding guide (and a starter CLAUDE.md if missing)
argument-hint: [path to repo, default current directory]
---

# /naki-onboard

Get to know the repository at `$ARGUMENTS` (or the current directory) and write a short onboarding guide, following
`naki-onboarding`. Read only, except for writing the guide when the user agrees.

## 1. Quick survey

- README, CONTRIBUTING, existing CLAUDE.md, docs folder, ADRs (`docs/adr/`).
- Manifests: `pyproject.toml`, `requirements*.txt`, `package.json`, `docker-compose.yml`, `Makefile`, CI workflows.
- Top-level layout with Glob; skip `node_modules`, virtual environments, build output and data folders.
- If the project has a rules skill (for example `naki-myapp`), read it and link it in the guide.

## 2. Structure

- If a Code Map exists, use `codemap_stats` for size and languages and `codemap_hubs` for the central modules. If it
  does not exist, suggest `/naki-codemap`.
- Otherwise, find entry points (app factory, main, CLI, routes, workers) by search.

## 3. Trace one real flow

Run the `naki-code-explorer` agent on one core user flow (for example "create an incident" or "login") so the guide
explains how a request moves through the layers.

## 4. Find how to work

- How to install, run, test, lint and build (from scripts, Makefile, CI).
- Conventions: naming, folder roles, error handling, test layout, commit style.
- Configuration and secrets: which env variables, where examples live (never copy real values).

## 5. Write the guide

```
# Onboarding: <repo>
## What it is
## Tech stack
## Layout
| Path | Role |
## Entry points
## Core flow: <name>
## How to run, test, lint
## Configuration
## Conventions
## Gotchas
## Where to start reading
```

Keep it under about 150 lines. Show it in chat first, then ask where to save it. If there is no CLAUDE.md, offer a
starter one with build/test commands and key rules. Do not overwrite existing docs without asking. Commit only when
the user asks.
