---
name: naki-sec-threat-hunting
description: Hypothesis-driven threat hunting with MITRE ATT&CK: forming hypotheses, choosing data sources, writing queries, stacking and pivoting, documenting results and turning hunts into detections. Use when proactively searching logs for undetected attacker activity, planning a hunt, or converting hunt findings into rules.
---

# Threat Hunting

## When to use

- You want to find attacker activity that existing rules missed.
- New threat intel describes a technique and you want to know if it happened in your environment.
- After an incident, to check whether the same actor is present elsewhere.
- You are building hunting queries or saved searches into a detection platform.

For reading specific log formats see `naki-sec-log-analysis`. For promoting a hunt into a rule see `naki-sec-detection-engineering`.

## Core rules

1. Start from a hypothesis that can be proven true or false with data you have.
2. Check data coverage first. A hunt over missing logs finds nothing and proves nothing.
3. Hunt for behavior (techniques), not only for indicators that change daily.
4. Baseline before judging. Rare is not the same as malicious, but malicious is often rare.
5. Every hunt ends with a written outcome, even "nothing found", plus the gaps you discovered.
6. A good hunt produces at least one durable artifact: a detection, a dashboard, or a logging fix.
7. Do not modify systems during a hunt. If you find live compromise, switch to incident response.

## Hypothesis sources

| Source | Example hypothesis |
|---|---|
| Threat intel | "An actor using T1566.001 attachments then T1204.002 is targeting our sector; check for Office spawning script hosts." |
| ATT&CK gap analysis | "We have no rule for T1053.005 Scheduled Task; attackers may use it for persistence." |
| Recent incident | "The attacker used a stolen service account; other service accounts may show interactive logins." |
| Environment change | "A new VPN appliance is exposed; check for T1190 exploitation attempts and new admin sessions." |
| Anomaly | "Outbound DNS volume doubled for 3 hosts; possible T1071.004 tunneling." |

Format: *Because [reason], an adversary may have [technique id], which would show as [observable] in [data source].*

## Workflow

1. **Hypothesis.** Write it in the format above with ATT&CK technique ids.
2. **Data check.** List required sources and confirm retention, coverage (which hosts send logs) and field quality.
3. **Query.** Start broad, then filter known-good. Keep each query saved with comments.
4. **Stack.** Count by value and look at the long tail (least frequent parent/child pairs, user agents, destinations).
5. **Pivot.** For each suspicious result, pivot by host, user, process, IP, hash and time.
6. **Judge.** Classify each lead: benign (with reason), suspicious (needs more), malicious (escalate).
7. **Record.** Use the hunt report template.
8. **Operationalize.** Turn reliable logic into a scheduled detection with known false positive filters.

## Hunt ideas by tactic

| Tactic | Technique | Observable | Data source |
|---|---|---|---|
| Initial access | T1190 Exploit Public-Facing Application | Web requests followed by new processes from the web server user | Web logs, process creation |
| Execution | T1059.001 PowerShell | `-enc`, `FromBase64String`, `IEX`, `DownloadString` in command lines | Process creation, script block logs (Windows 4104) |
| Persistence | T1053.005 Scheduled Task | Task actions pointing to `AppData`, `Temp`, `ProgramData` | Windows 4698, Task Scheduler log |
| Persistence | T1543.003 Windows Service | New service with binary outside system dirs | Windows 7045 |
| Persistence | T1098 Account Manipulation | Users added to admin groups outside change windows | Windows 4728/4732/4756, cloud audit |
| Privilege escalation | T1548 Abuse Elevation Control | `sudo` by users who never used it, setuid changes | auth.log, auditd |
| Defense evasion | T1070.001 Clear Windows Event Logs | Event 1102 or 104 | Security and System logs |
| Credential access | T1003.001 LSASS Memory | Non-standard processes opening lsass handle | EDR, Sysmon event 10 |
| Discovery | T1087 Account Discovery | Bursts of `net user`, `whoami /groups`, LDAP queries from workstations | Process creation, LDAP logs |
| Lateral movement | T1021.001 RDP / T1021.002 SMB | Workstation-to-workstation logons type 10 or 3 | Windows 4624, network flow |
| Command and control | T1071 Application Layer Protocol | Regular beacon intervals, low byte variance, rare domains | Proxy, DNS, flow |
| Exfiltration | T1567 Exfiltration to Web Service | Large uploads to file sharing or paste sites | Proxy, CASB |
| Impact | T1486 Data Encrypted for Impact | Mass file renames, shadow copy deletion (`vssadmin delete shadows`) | EDR, file audit |

## Query patterns

Stacking rare parent/child process pairs (SQL-like, adapt to your engine):

```sql
SELECT parent_image, image, COUNT(*) AS n, COUNT(DISTINCT host) AS hosts
FROM process_events
WHERE ts > now() - interval '14 days'
GROUP BY parent_image, image
HAVING COUNT(DISTINCT host) <= 2
ORDER BY n ASC;
```

Beacon detection idea: for each (host, destination), compute the standard deviation of intervals between connections; low deviation with many connections and small payloads is a lead.

```python
import statistics

def beacon_score(timestamps: list[float]) -> float | None:
    if len(timestamps) < 20:
        return None
    gaps = [b - a for a, b in zip(timestamps, timestamps[1:])]
    mean = statistics.mean(gaps)
    return statistics.pstdev(gaps) / mean if mean else None  # near 0 = regular
```

First-seen logic: flag a value (domain, user agent, admin tool, country) the first time it appears for a user or host within a 30 to 90 day baseline.

## Hunt report template

```markdown
# Hunt H-YYYY-NN: <title>
- Hypothesis: <format above>
- ATT&CK: <ids>
- Data sources and window: <sources, dates, coverage gaps>
- Queries: <links or text>
- Results: <n leads; each with benign / suspicious / malicious and reason>
- Escalations: <incident ids or none>
- Gaps found: <missing logs, missing fields>
- Outputs: <new detection ids, dashboards, logging tickets>
```

## Checklist

- [ ] Hypothesis is falsifiable and tied to technique ids
- [ ] Data coverage confirmed for the whole window
- [ ] Known-good filtered with documented reasons
- [ ] Every lead classified
- [ ] Report written, including negative results
- [ ] At least one detection, dashboard or logging fix created

## Common mistakes

- Hunting only for yesterday's IOC list; that is a search, not a hunt.
- Declaring "no compromise" when half the hosts were not sending logs.
- Filtering out all signed binaries; attackers use legitimate tools (living off the land).
- Leaving a good query in a notebook instead of making it a scheduled rule.
