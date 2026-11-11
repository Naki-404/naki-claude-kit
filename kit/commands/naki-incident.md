---
description: Triage a security incident or alert the user describes or points to and produce a structured incident report
argument-hint: <alert description or path to logs/evidence>
---

# /naki-incident

Triage the incident or alert in `$ARGUMENTS` and write an incident report. Defensive work only: analyze, advise,
document. Do not execute containment actions, contact attacker infrastructure or submit indicators to external
services unless the user explicitly asks.

## 1. Intake

- Collect: what was observed, when, by whom, affected assets and accounts, paths to logs or evidence.
- If evidence paths are missing, ask for them. If the user only has a description, proceed and mark the report as
  based on reported information.
- Read the project rules skill if present (for example `naki-myapp`).

## 2. Preserve evidence

Before analysis, record path, size and SHA-256 of each evidence file (`sha256sum` in Git Bash or `Get-FileHash` in
PowerShell). Work read-only. Follow `naki-sec-forensics`.

## 3. Analyze

Run the `naki-incident-analyst` agent with the description, evidence paths and log time zones. Point it to the
relevant skills:
- `naki-sec-alert-triage` for severity and true/false positive reasoning
- `naki-sec-log-analysis` for timelines from web, auth, cloud and system logs
- `naki-sec-threat-intel` for indicators and confidence
- `naki-sec-phishing` when the entry point is an email
- `naki-sec-cloud-containers` for cloud or Kubernetes activity
- `naki-sec-incident-response` for containment, eradication and recovery

If the scope is unclear, also run `naki-threat-hunter` with a hypothesis built from the first findings to search for
the same activity elsewhere in the provided data.

## 4. Report

```
# Incident report: <short title>
Status: Open | Contained | Closed    Severity: ...    Confidence: ...

## Summary
<what happened, impact, current state, in 4-6 sentences>

## Timeline (UTC)
| Time | Host / account | Event | Evidence |

## Evidence
| Item | Path | SHA-256 | Notes |

## ATT&CK mapping
| Tactic | Technique (id) | Evidence | Fact / inferred |

## Scope
Affected / checked and clean / unknown

## Containment
<immediate actions, owner, side effects>

## Eradication
<remove persistence, fix entry point, rotate credentials>

## Recovery
<restore, monitoring, criteria to close>

## Detection improvements
<rules to add, see naki-sec-detection-engineering>

## Open questions
1. ...
```

Label facts and inferences. Do not include secret values or full personal data; reference them. Offer to save the
report as a file and ask where.
