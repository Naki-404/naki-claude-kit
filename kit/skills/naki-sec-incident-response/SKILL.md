---
name: naki-sec-incident-response
description: Security incident response lifecycle following NIST SP 800-61: declaration, triage, scoping, containment, eradication, recovery, lessons learned and communication. Use when a security alert is confirmed or likely real, when writing or reviewing an IR playbook, or when building incident workflows into a detection platform.
---

# Security Incident Response

## When to use

- An alert has been triaged as a likely true positive and needs coordinated handling.
- You are writing a playbook (ATT&CK technique to response actions, D3FEND countermeasures).
- You are designing incident objects, states and timelines in a detection or case management system.
- You are writing the post-incident report or the lessons-learned review.

For deciding whether an alert is real, use `naki-sec-alert-triage` first. For evidence handling, see `naki-sec-forensics`. Follow the project rules skill if the project has one (for example `naki-myapp`).

## Core rules

1. Declare early. Opening an incident that turns out benign is cheap; a late declaration loses evidence and time.
2. One incident commander (IC) owns decisions. Others investigate, contain, or communicate.
3. Preserve evidence before you change anything you can avoid changing. Snapshot, export logs, record hashes.
4. Contain before you eradicate. Removing malware while the attacker still holds valid credentials only tips them off.
5. Assume the scope is wider than the first alert. Look for the same indicator on every host, account and tenant.
6. Every action goes into the timeline with UTC time, actor, target and result.
7. Use out-of-band communication if the normal channel (mail, chat) may be compromised.
8. Never pay, negotiate, or contact the attacker without legal and management approval.
9. Recovery is not done until monitoring confirms the attacker is gone for an agreed watch period.

## Lifecycle (NIST 800-61)

| Phase | Goal | Main outputs |
|---|---|---|
| Preparation | Be ready before it happens | Playbooks, contact list, log retention, access for responders |
| Detection and analysis | Confirm, classify, scope | Incident record, severity, initial timeline, affected assets |
| Containment | Stop spread and damage | Isolated hosts, disabled accounts, blocked indicators |
| Eradication | Remove attacker foothold | Cleaned or rebuilt systems, rotated secrets, closed entry point |
| Recovery | Return to normal safely | Restored services, heightened monitoring, sign-off |
| Post-incident | Learn and improve | Report, root cause, new detections, action items with owners |

## Severity matrix

| Severity | Typical criteria | Response target |
|---|---|---|
| SEV1 critical | Confirmed data exfiltration, ransomware spreading, domain admin or cloud root compromise, production down | Immediate, 24/7, management informed within 1 hour |
| SEV2 high | Confirmed compromise of one host or privileged account, no evidence of spread yet | Start within 1 hour |
| SEV3 medium | Compromise of a low-privilege account or single workstation, contained malware | Same business day |
| SEV4 low | Policy violation, failed attack with no impact, suspicious but unconfirmed | Next business days |

Raise severity when: regulated data (personal, payment, health) is involved, the asset is internet-facing, or the actor shows hands-on-keyboard behavior.

## Workflow

1. **Declare.** Create the incident record: id, title, detection source, reporter, IC, severity, status `open`.
2. **Stabilize facts.** Write down what is known, what is assumed, and what is unknown. Keep these lists separate.
3. **Preserve.** Export relevant logs (auth, endpoint, cloud audit, proxy) for the window before first sign. Snapshot affected VMs or disks if possible.
4. **Scope.** For each indicator (IP, domain, hash, account, user agent), search the whole estate. Build an affected asset list.
5. **Map to ATT&CK.** Tag observed behaviors with technique ids. This guides where to look next (for example, after T1078 Valid Accounts, check T1098 Account Manipulation and T1136 Create Account).
6. **Contain.** Choose short-term actions (below). Confirm each one worked.
7. **Eradicate.** Remove persistence, patch the entry point, rotate every credential that touched an affected system.
8. **Recover.** Restore from known-good backups or rebuild. Re-enable accounts with new credentials and MFA. Monitor closely.
9. **Close.** Final report, root cause, action items, new or tuned detections (see `naki-sec-detection-engineering`).

## Containment options

| Situation | Action | D3FEND idea | Side effect to weigh |
|---|---|---|---|
| Compromised user account | Disable, revoke sessions and refresh tokens, reset password, re-enroll MFA | Credential revocation | User downtime |
| Compromised host | Network isolate via EDR, keep powered on for memory | Network isolation | Service loss if a server |
| Leaked API key or cloud key | Revoke and rotate, review usage logs since creation | Credential rotation | Integrations break until updated |
| Malicious IP or domain | Block at firewall, proxy and DNS | Network traffic filtering | Shared hosting false blocks |
| Web shell or exploited app | Take app offline or put behind WAF rule, preserve files | Inbound traffic filtering | Outage |
| Ransomware spreading | Segment network, disable SMB between segments, pause backups sync | Network segmentation | Broad disruption, protects backups |

Do not shut down a host as the first move unless destruction is ongoing; you lose volatile evidence.

## Communication

- Internal updates on a fixed cadence (SEV1: every hour, SEV2: every 4 hours), even if there is nothing new.
- Keep a single source of truth (the incident record), not parallel chat threads.
- Legal and privacy decide on external notification; record the time you became aware of a personal data breach, because many regulations count notification deadlines from that moment (for example 72 hours under GDPR).
- Never put indicators, credentials or customer data in public tickets or public channels.

Status update template:

```text
[INC-2026-014] SEV2 | Status: containment | Update 3 | 14:00 UTC
Known: account svc-report used from unfamiliar IP 203.0.113.50, read 2 storage buckets.
Done: key revoked 13:10, sessions revoked 13:12, IP blocked 13:20.
Next: review bucket access logs for downloads, check other keys created by this account.
Open questions: initial access vector. Next update 18:00 UTC.
```

## Incident report template

```markdown
# Incident INC-YYYY-NNN: <short title>
- Severity / final classification:
- Detection: source, rule, time detected, time of first malicious activity (dwell time)
- Summary: 3 to 5 sentences, non-technical
- Timeline (UTC): time | source | event | actor
- Affected assets and data:
- ATT&CK techniques observed:
- Root cause and entry point:
- Containment, eradication, recovery actions (with times):
- What worked / what did not:
- Action items: item | owner | due date
- New or tuned detections:
```

## Building IR into a platform

- Model incident states explicitly: `open`, `triage`, `contained`, `eradicated`, `recovered`, `closed`, plus `false_positive`.
- Link incidents to the alerts and events that created them; never copy and detach.
- Attach playbooks by ATT&CK technique; each step has an owner, status and timestamp.
- Record every automated action (block, disable) with who approved it. Destructive automatic actions need a human approval step.
- Compute metrics: mean time to detect, to contain, to recover; false positive rate per rule.

## Checklist

- [ ] Incident record with IC, severity, status and timeline
- [ ] Evidence exported before containment changes
- [ ] All indicators searched estate-wide
- [ ] Every credential on affected systems rotated
- [ ] Persistence mechanisms checked (scheduled tasks, services, startup, new accounts, OAuth apps, cloud roles)
- [ ] Entry point closed
- [ ] Watch period with extra monitoring agreed and completed
- [ ] Report written, action items assigned, detections updated

## Common mistakes

- Reimaging the first host and declaring victory while the attacker keeps a second foothold.
- Resetting a password but not revoking existing sessions, tokens or API keys.
- Mixing local time zones in the timeline.
- Discussing the incident in a mailbox that the attacker controls.
- Writing lessons learned without owners and dates, so nothing changes.
