---
name: naki-sec-vuln-management
description: Vulnerability management from scan to closure: asset inventory, scanning, prioritizing with CVSS, EPSS and the KEV catalog, remediation SLAs, patch verification and risk exceptions. Use when triaging scanner output or dependency advisories, setting fix deadlines, planning patches, or approving an exception.
---

# Vulnerability Management

The goal is not zero findings. The goal is that the vulnerabilities most likely to be exploited on the assets that matter
are fixed first, within a known deadline, and that every open finding has an owner.

## When to use

- A scanner, dependency audit (`pip-audit`, `npm audit`, image scanner) or advisory produced a list of findings.
- Deciding what to fix this week versus this quarter.
- Defining or checking remediation SLAs.
- Someone asks to accept a risk instead of fixing it.

## Core rules

1. No inventory, no vulnerability management. Know which assets, images and dependencies exist and who owns them.
2. CVSS measures severity, not risk. Combine it with exploitation likelihood (EPSS), known exploitation (KEV) and
   asset exposure and criticality.
3. Anything on the CISA Known Exploited Vulnerabilities catalog on an exposed asset is urgent, whatever its CVSS.
4. Every finding has an owner, a due date and a status. Unowned findings are the real backlog.
5. A fix is closed only after a rescan or test proves it, not when a ticket says "patched".
6. Exceptions are time-limited, approved by the asset owner, and carry compensating controls.
7. Deduplicate: one root cause (one library version) is one work item, even if it appears in 40 images.

## Inputs to prioritization

| Signal | What it tells you | Where it comes from |
|---|---|---|
| CVSS base score | Technical severity if exploited | NVD, vendor advisory |
| EPSS probability | Likelihood of exploitation in the next 30 days | EPSS daily data |
| KEV listed | Exploitation seen in the wild | CISA KEV catalog |
| Exposure | Internet facing, internal, isolated | Asset inventory, network config |
| Asset criticality | Business or data impact | Asset owner, data classification |
| Reachability | Is the vulnerable code path actually used | Code review, SCA reachability, config |
| Fix availability | Patch, upgrade, config change, none | Advisory |

## Priority decision table

| Condition | Priority | SLA (target) |
|---|---|---|
| KEV listed and internet facing | P1 | 72 hours (mitigate within 24 hours) |
| KEV listed, internal only | P2 | 7 days |
| CVSS >= 9.0 and EPSS >= 0.1, exposed | P1 | 72 hours |
| CVSS >= 7.0 and (EPSS >= 0.1 or exposed) | P2 | 14 days |
| CVSS >= 7.0, internal, low EPSS | P3 | 30 days |
| CVSS 4.0 to 6.9 | P3 | 60 days |
| CVSS < 4.0, or not reachable | P4 | next regular update cycle |

Adjust the thresholds to your organisation, but write them down. Reachability can lower priority by one level only with
evidence (for example the vulnerable function is not imported, or the feature flag is off everywhere).

## Workflow

1. **Inventory.** Pull assets, container images, and dependency manifests (`requirements.txt`, lock files,
   `package-lock.json`). Tag each with owner, exposure and criticality.
2. **Scan.** Run scanners on a schedule and in CI (see `naki-sec-devsecops`). Store raw output with the scan date.
3. **Normalize.** Map findings to `(asset, component, version, CVE)`. Merge duplicates across scanners.
4. **Enrich.** Add EPSS, KEV flag, fix version, exploit maturity.
5. **Prioritize.** Apply the decision table; record the inputs that produced the priority.
6. **Assign.** Create one ticket per root cause with owner and due date.
7. **Remediate.** Upgrade, patch, change config, or apply a mitigation (WAF rule, feature off, network block).
8. **Verify.** Rescan or run a targeted test. Close only on evidence.
9. **Report.** Track open by priority, SLA breaches, mean time to remediate, and exception count.

## Dependency upgrades in practice

```bash
# Python: list known vulnerable packages in the current environment
pip-audit -r requirements.txt

# Node: production dependencies only
npm audit --omit=dev

# Container image (example scanner)
trivy image --severity HIGH,CRITICAL myapp:latest
```

- Upgrade to the lowest fixed version first if a major upgrade is risky, then plan the major upgrade separately.
- Run the full test suite after upgrading. Pin the new version in the lock file.
- For transitive dependencies, upgrade the parent or use an override/constraint file, and note it for later removal.

## Exception (risk acceptance) workflow

1. Requester states why the fix cannot be done by the SLA (no patch, breaking change, vendor appliance).
2. Security proposes compensating controls (isolation, WAF rule, monitoring rule, disabling the feature).
3. Asset owner approves and accepts the residual risk in writing.
4. Exception expires (30 to 90 days). On expiry it is re-reviewed, never auto-renewed.
5. A detection or monitoring rule for exploitation attempts is added where possible (see `naki-sec-detection-engineering`).

## Checklist

- [ ] Every finding mapped to an asset with an owner.
- [ ] KEV and EPSS enrichment applied before sorting.
- [ ] Duplicates merged into root-cause tickets.
- [ ] Due dates set from the written SLA table.
- [ ] Closure backed by a rescan or test result.
- [ ] Exceptions have expiry, approver and compensating controls.
- [ ] Metrics reviewed monthly; SLA breaches escalated.

## Common mistakes

- Sorting by CVSS alone and spending weeks on unreachable 9.8s while a KEV 7.5 on the login page waits.
- Counting findings instead of root causes, which inflates the backlog and hides progress.
- Closing tickets on "deployed" without verifying the running version.
- Permanent exceptions that nobody reviews.
- Scanning only production and ignoring base images and CI runners.
- Ignoring dev dependencies that run in CI with access to secrets.

## Finding report template

```markdown
## <CVE id> in <component> <version>
- Assets affected (count, examples):
- Exposure / criticality:
- CVSS / EPSS / KEV:
- Reachable: yes / no / unknown (evidence)
- Priority and due date:
- Fix: upgrade to <version> / config change / mitigation
- Owner:
- Verification: <scan id or test> on <date>
- Status: open / in progress / fixed / exception until <date>
```

Follow the project rules skill if the project has one (for example `naki-myapp`).
