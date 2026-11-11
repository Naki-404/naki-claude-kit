---
description: Build a feature end to end: explore the code, design, get approval, implement test-first, verify
argument-hint: <feature description>
---

# /naki-feature

Build the feature described in `$ARGUMENTS` in five phases. Do not skip the approval gate.

## Phase 1: Understand

1. Read the project rules skill if present (for example `naki-myapp`).
2. Restate the feature: user-visible behavior, inputs, outputs, edge cases, non-goals.
3. Ask clarifying questions if requirements are unclear. Wait for answers.

## Phase 2: Explore

1. Run the `naki-code-explorer` agent on the closest existing feature or the area that will change. Ask it for entry
   points, call chain, data flow and tests.
2. Apply `naki-search-first`: check whether the codebase or a well-known library already solves part of the task.
3. Read the key files the explorer lists before designing.

## Phase 3: Design

1. For simple features, write the design yourself. For features with real trade-offs, run `naki-architect`.
2. Present: files to add or change, data model and API changes (`naki-api-design`, `naki-postgres`), error handling
   (`naki-error-handling`), test plan, risks.
3. If the decision is hard to reverse, offer an ADR (`naki-adr`).
4. **Stop and ask for approval.** Do not write code before an explicit "yes".

## Phase 4: Implement test-first

Follow `naki-tdd`:
1. Write a failing test for the first behavior. Run it and confirm it fails for the right reason.
2. Write the minimal code to pass. Run the test.
3. Refactor while green.
4. Repeat for each behavior, including error paths.

Use the matching skill for the stack: `naki-python`, `naki-fastapi`, `naki-react`, `naki-typescript`,
`naki-frontend-testing`, `naki-python-testing`, `naki-e2e-playwright`.

If a guard hook blocks an action with a `kit:` reason, follow the reason and ask the user. Do not work around it.

## Phase 5: Verify and review

1. Run the project's tests and linters, and the full `naki-verify` checklist.
2. Run `naki-code-reviewer` on the diff, plus `naki-security-reviewer` if the feature touches input handling, auth,
   files, secrets or outbound requests. Fix Critical and High findings, then re-run tests.
3. Report:

```
## Feature: <name>
Changed files: ...
Tests added: ...
Verification: PASS | FAIL (details)
Review findings fixed: ...
Open items: ...
```

Commit only when the user asks.
