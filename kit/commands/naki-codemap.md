---
description: Build or refresh the Code Map (symbols, calls, imports; local, no LLM) and summarize the codebase structure
argument-hint: [repo path, default from .claude/kit.json or current repo]
---

# /naki-codemap

Build or refresh the local Code Map and give a short structural summary. The build is local and uses no LLM or
network.

## 1. Choose repositories

In order:
1. Paths given in `$ARGUMENTS`.
2. Otherwise the project's `.claude/kit.json`, key `codemap.dirs` (a list of repo paths, relative to the project
   root or absolute).
3. Otherwise the current git repository root (`git rev-parse --show-toplevel`).

Skip paths that do not exist and report them.

## 2. Build

For each repository run:

```
python ~/.claude/naki-kit/tools/codemap.py build <repo>
```

- On Windows use Git Bash so `~` expands, or pass the full path to `codemap.py`.
- Run builds one after another and record the exit code and the last lines of output for each.
- If the script is missing, say the kit tools are not installed and stop.
- If a build fails, show the error and continue with the next repo.
- If a guard hook blocks the command with a `kit:` reason, follow it and ask the user.

## 3. Summarize

Use the Code Map MCP tools:
- `codemap_stats`: files, symbols, edges, languages per repo.
- `codemap_hubs`: the most connected symbols (top 10 to 15).
- Optionally `codemap_file` on the top hub files to describe what they hold.

If the MCP tools are not available in this session, say so and summarize from the build output only.

## 4. Report

```
## Code Map
| Repo | Status | Files | Symbols | Edges | Languages |
|---|---|---|---|---|---|

### Hubs (most connected)
| Symbol | File | Connections | Role (one line) |
|---|---|---|---|

### Observations
- <central modules, possible god objects, isolated areas>

### Next
- Use codemap_search, codemap_symbol and codemap_path to explore.
```

Do not edit source files. The Code Map is derived data; there is nothing to commit unless the project tracks it and
the user asks.
