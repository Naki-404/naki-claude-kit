---
description: Restate the task, list risks and a phased plan, then wait for an explicit "yes" before writing any code
argument-hint: <task description>
---

# /naki-plan

Plan the task in `$ARGUMENTS`. Do not write, edit or generate implementation code in this command until the user
answers with an explicit "yes" (or "go", "approved"). Anything else, including silence or questions, means wait.

## Steps

1. **Load project rules.** If the project has a rules skill (for example `naki-myapp`), read it first. Its
   constraints go into the plan.
2. **Clarify.** If the task is ambiguous in a way that changes the plan, ask up to three short questions and stop.
3. **Explore.** For non-trivial tasks, use the `naki-planner` agent (and `naki-code-explorer` if the flow is
   unfamiliar). For small tasks, read the relevant files yourself. If a Code Map exists, use `codemap_search` and
   `codemap_symbol` to find callers and blast radius.
4. **Assess impact** for cross-module, schema, auth or public API changes using `naki-change-impact`.
5. **Write the plan** in this format:

```
## Task
<restated in 2-3 sentences; in scope / out of scope>

## Risks
| Risk | Impact | Mitigation |
|---|---|---|

## Plan
Phase 1: <name>: steps, files, tests, done when
Phase 2: ...

## Tests and verification
<tests to add, commands to run (see naki-verify)>

## Open questions
1. ...

Reply "yes" to start, or tell me what to change.
```

6. **Stop.** End the turn after the plan.

## After approval

- Implement phase by phase, test-first where practical (`naki-tdd`).
- After each phase, run the project's tests and linters and report results before moving on.
- If reality differs from the plan (new risk, bigger scope), stop and present the change before continuing.
- If a guard hook blocks an action with a `kit:` reason, follow it and ask the user; do not work around it.
- Commit only when the user asks.

## If the user changes the plan

Update the plan, show the diff of what changed, and wait for "yes" again.
