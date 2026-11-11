---
name: naki-sec-alert-triage
description: SOC alert triage: severity scoring, true and false positive reasoning, enrichment, classification, escalation and documenting the decision. Use when investigating a security alert, deciding if an event is real, designing triage categories or LLM triage prompts, or tuning noisy rules.
---

# Security Alert Triage

## When to use

- An alert fired and someone has to decide: close, investigate, or escalate.
- You are designing triage classes for a detection pipeline (for example `bug`, `expected`, `data_infra`, `security`, `needs_human`).
- You are writing or evaluating an LLM triage step and need clear decision rules.
- A rule is noisy and you need evidence to tune it.

Confirmed incidents move to `naki-sec-incident-response`. Rule tuning details live in `naki-sec-detection-engineering`.

## Core rules

1. Triage answers three questions: Is it real? How bad is it? Who acts next?
2. Decide from evidence, not from the alert title. Read the raw event.
3. Every closure needs a written reason that another analyst could verify.
4. "Benign true positive" is a real class: the rule worked, the activity is authorized. Record it separately from false positives.
5. When unsure, escalate with what you checked. A silent close of an unclear alert is the worst outcome.
6. Time-box: if the first 15 minutes do not resolve it, escalate or open a case.
7. Never run suspicious files or visit suspicious links from your workstation. Use sandboxes and reputation lookups.

## Outcome classes

| Class | Meaning | Action |
|---|---|---|
| True positive (malicious) | Activity is real and unauthorized | Escalate or open incident |
| Benign true positive | Activity is real and authorized (pentest, admin task, scanner) | Close, consider allowlist with expiry |
| False positive | Rule matched something it should not | Close, file tuning request |
| Undetermined | Not enough data | Escalate or `needs_human`, list missing data |

Mapping to a platform's classes: `security` = true positive candidate; `expected` = benign true positive; `bug` and `data_infra` = application or pipeline faults that look anomalous (failed jobs, schema errors, disk full); `needs_human` = undetermined or high impact.

## Workflow

1. **Read the alert.** Rule name, logic, raw event, timestamp (UTC), host, user, source and destination.
2. **Check the rule.** What exactly does it match? Known false positive notes? Recent changes?
3. **Enrich entities.**
   - User: role, department, privilege, normal working hours, recent password or MFA changes, travel.
   - Host: owner, criticality, OS, internet-facing, EDR status.
   - IP / domain: internal or external, ASN, geolocation, reputation, first seen in your logs.
   - File: hash reputation, signer, path, prevalence across fleet.
   - Process: parent, command line, user context.
4. **Look around in time.** Events from the same user or host 30 minutes before and after. What led here, what followed?
5. **Look around in space.** Same indicator on other hosts or accounts?
6. **Decide** using the tables below.
7. **Document** with the template.

## Severity scoring

Score = impact of the asset x confidence of malice, adjusted by stage.

| Factor | Low | Medium | High |
|---|---|---|---|
| Asset criticality | Test VM, kiosk | Standard workstation, internal app | Domain controller, prod database, CI/CD, identity provider, cloud admin |
| Account privilege | Standard user | Power user, service account | Admin, root, global admin |
| Confidence | Single weak signal | Several signals or known-bad indicator | Confirmed malicious behavior chain |
| Kill chain stage | Recon, failed attempt | Execution, persistence | Credential access, lateral movement, exfiltration, impact |

Rule of thumb: any high confidence plus high criticality is critical. A successful login after a brute-force burst is never low.

## Decision hints by alert type

| Alert | Points to true positive | Points to false or benign |
|---|---|---|
| Many failed logins then success (T1110) | Success from same source, new geo, MFA fatigue prompts | Known user mistyping after password change, same device |
| Impossible travel | New device, unfamiliar ASN, legacy auth protocol | Corporate VPN egress, mobile carrier IP, cloud proxy |
| Encoded PowerShell (T1059.001) | Download cradle, parent is Office or browser, outbound connection after | Signed management tool, known deployment script, runs fleet-wide on schedule |
| New admin account (T1136, T1098) | Created outside change window, by unusual actor, quickly used | Ticketed change, created by provisioning system |
| Scheduled task created (T1053.005) | Runs from temp or user profile, obfuscated arguments | Software updater, signed binary in program files |
| Large outbound transfer (T1048, T1567) | Unusual destination, archive files, off-hours | Backup job, known sync tool, matching volume history |
| Web attack signature (T1190) | 200 response with abnormal size, follow-up requests from same IP, new files on server | 404 or 403 responses, generic scanner user agent, WAF blocked |
| Cloud key used from new IP (T1078.004) | API calls to list or read storage, create users or keys | CI runner IP range change, documented migration |

## Building triage into a pipeline

- Give the classifier the raw event, rule description, entity enrichment, and a short window of related events. Do not give only the alert title.
- Require structured output: `class`, `confidence` (0 to 1), `severity`, `reasons` (list of evidence lines), `missing_data`.
- Route low confidence or high severity to `needs_human` regardless of class.
- Never let an automated triage step close a `security` candidate on its own; it can only lower priority.
- Log every decision with model or rule version so you can audit and re-run.
- Measure per class: precision, recall, and how often humans override. Track this per rule.

## Documentation template

```text
Alert: <rule name> | id <alert id> | <UTC time>
Entities: user=<u> host=<h> src=<ip> dst=<ip/domain>
Checked:
- raw event: <key fields>
- user context: <role, hours, recent changes>
- related events +/-30 min: <summary>
- reputation: <result and source type>
- fleet prevalence: <n hosts>
Decision: <TP / benign TP / FP / undetermined>, severity <x>
Reason: <one or two sentences tied to evidence above>
Next: <escalated to / tuning request / closed>
```

## Checklist

- [ ] Raw event read, not only the title
- [ ] User, host and network entities enriched
- [ ] Time window before and after reviewed
- [ ] Same indicator searched across the estate
- [ ] Class and severity chosen with written evidence
- [ ] Tuning request filed for false positives

## Common mistakes

- Closing because "this rule is always noisy" without checking this instance.
- Trusting geolocation alone; VPNs and carriers move users around.
- Allowlisting a whole parent process or user forever instead of a narrow pattern with an expiry date.
- Treating application errors (`bug`, `data_infra`) as security alerts, or the reverse: an attacker probing produces errors too, so check source and pattern.
- Not recording benign true positives, which hides how often admins do risky things.
