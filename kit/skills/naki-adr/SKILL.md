---
name: naki-adr
description: Architecture decision records: when a decision deserves one, a short template, numbering, status changes and an index. Use when choosing between technologies or designs, reversing an earlier choice, or when someone asks why the system is built a certain way.
---

# Architecture Decision Records

An ADR is a short, dated note that records one significant decision, the context that forced it, the options considered and the consequences accepted. It answers "why is it like this?" months later.

## When to use

Write an ADR when a decision is:

- Hard to reverse: database, framework, message broker, hosting, auth model.
- Cross-cutting: error format, logging, API versioning, module boundaries.
- Contested: the team discussed alternatives and picked one.
- Surprising: a future reader would expect a different choice.
- A deliberate trade-off: "we accept X to get Y".

Do not write one for routine choices that are easy to change (a helper library, a variable name, a CSS approach in one component).

## Core rules

1. One decision per record.
2. Records are immutable once accepted. To change a decision, write a new ADR that supersedes the old one and update the old one's status line only.
3. Write the context honestly, including constraints like deadline, budget, team skills and hardware.
4. List real alternatives, including "do nothing", with why each lost.
5. Consequences include the bad ones.
6. Keep it short: one page is the target.
7. Store ADRs in the repository next to the code, so they are reviewed in pull requests.

## Layout

```
docs/adr/
  README.md                       index
  0001-record-architecture-decisions.md
  0002-use-postgresql.md
  0003-rules-first-llm-fallback.md
```

- Four-digit sequence, never reused.
- Lowercase, hyphenated title in the file name.
- If the project already has another location or format, follow it.

## Template

```markdown
# ADR-0003: Rules first, LLM as fallback for alert triage

Status: Accepted
Date: 2026-03-14
Deciders: <names or roles>
Supersedes: none
Superseded by: none

## Context
What problem, what forces: requirements, constraints, numbers.
Keep facts verifiable (link the benchmark script, issue or measurement).

## Decision
What we will do, stated in one or two sentences, active voice.

## Alternatives considered
| Option | Pros | Cons | Why not |
|---|---|---|---|
| LLM for every alert | simplest code | cost, latency | budget |
| Rules only | cheap, predictable | misses new patterns | recall too low |

## Consequences
Positive:
- ...
Negative:
- ...
Follow-ups:
- tasks or checks this decision creates

## Validation
How we will know it was right (metric, review date).
```

## Statuses

| Status | Meaning |
|---|---|
| Proposed | Under discussion, can still change |
| Accepted | In force |
| Rejected | Considered and declined (kept for history) |
| Deprecated | No longer relevant, nothing replaces it |
| Superseded | Replaced by a newer ADR, linked by number |

## Index

`docs/adr/README.md` lists every record:

```markdown
| # | Title | Status | Date |
|---|---|---|---|
| 0001 | Record architecture decisions | Accepted | 2026-01-10 |
| 0002 | Use PostgreSQL | Accepted | 2026-01-12 |
| 0003 | Rules first, LLM fallback | Accepted | 2026-03-14 |
```

Update the index in the same change that adds or supersedes a record.

## Workflow

1. Notice the decision point (a design discussion, a "should we use X or Y", a reversal).
2. Check existing ADRs for related or conflicting decisions.
3. Draft as Proposed, with context and alternatives filled in before the decision.
4. Ask the user (or team) to decide; do not mark Accepted on your own.
5. On acceptance, set the status and date, add to the index.
6. If it replaces an older ADR, set the old one to "Superseded by ADR-NNNN" and link back.
7. Reference the ADR number in the related pull request and in code comments where the choice looks odd.

## Checklist

- [ ] Decision is significant and hard to reverse
- [ ] Context includes constraints and evidence
- [ ] At least two real alternatives with reasons
- [ ] Negative consequences listed
- [ ] Status and date set; index updated
- [ ] Superseded records linked both ways

## Common mistakes

- Writing the ADR after the fact with alternatives invented to look thorough.
- Editing an accepted record to match a new decision, which erases history.
- Recording implementation details instead of the decision.
- Vague context ("for performance") with no numbers.
- No owner or date, so nobody knows if it is still valid.

## Related

- `naki-change-impact` checks whether a change contradicts an accepted ADR.
- `naki-onboarding` reads ADRs early to learn why things are the way they are.
