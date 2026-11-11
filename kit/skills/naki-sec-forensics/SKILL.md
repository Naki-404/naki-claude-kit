---
name: naki-sec-forensics
description: First-response digital forensics: order of volatility, evidence preservation and hashing, chain of custody, building timelines, and triage of hosts, cloud accounts and logs without destroying evidence. Use when a host or account may be compromised, before reimaging or deleting anything, or when an incident needs a defensible timeline.
---

# First Response Forensics

The first responder's job is to preserve evidence and answer "what happened, when, and how far did it spread" without
making things worse. Deep malware analysis and court work belong to specialists; good first response makes their work
possible.

## When to use

- An alert or incident points to a compromised host, account, container or cloud resource.
- Someone wants to reimage, terminate or "clean up" a system that may hold evidence.
- You need a timeline for an incident report (see `naki-sec-incident-response`).
- Legal, HR or insurance may later need the evidence.

## Core rules

1. Preserve before you change. Do not reboot, reimage, delete or run cleanup tools until evidence is collected or the
   incident lead accepts the loss.
2. Collect in order of volatility: memory and live state first, disk and logs next, backups and archives last.
3. Work on copies. Hash every artifact (SHA-256) at collection and verify the hash before analysis.
4. Keep a chain of custody record for every item: who, what, when, where stored, every transfer.
5. Write notes as you go, with UTC timestamps. Your actions also leave traces; record them so they are not mistaken
   for attacker activity.
6. Use trusted tools from external media or a known-good share, not binaries from the suspect system.
7. Containment and preservation must be balanced: isolate the network (EDR isolation, security group) rather than
   powering off, when possible.
8. Normalize all times to UTC and note each source's original time zone and clock offset.

## Order of volatility

| Order | Evidence | Lost when |
|---|---|---|
| 1 | CPU state, memory, running processes, network connections | Reboot or power off |
| 2 | Logged-in sessions, open files, clipboard, temp files | Logout, reboot |
| 3 | Local disk (file system, registry, browser data, local logs) | Reimage, overwrite, rotation |
| 4 | Remote logs (SIEM, cloud audit logs, proxy, DNS) | Retention expiry |
| 5 | Backups, snapshots, archived media | Retention policy |

## Decision table: what to do with a suspect system

| Situation | Action |
|---|---|
| Active attacker, data leaving now | Network isolate immediately, then collect memory and triage data |
| Suspected compromise, no active harm | Collect memory and triage package, then isolate |
| Cloud VM | Snapshot disks, capture instance metadata and audit logs, then isolate with a security group |
| Container | Save the container filesystem and logs (`docker export`, `docker logs`), capture image digest, then stop |
| SaaS or cloud account | Export audit logs first, then revoke sessions and rotate credentials |
| Business critical, cannot go offline | Collect live data, increase monitoring, plan a maintenance window |

## Workflow

1. **Open the case.** Case id, incident lead, scope, legal hold needed or not. Start a notes file.
2. **Identify sources.** Hosts, accounts, logs, cloud resources involved. Check retention and extend it now if close.
3. **Collect volatile data.** Memory image and live state with trusted tools. Record tool name and version.
4. **Collect triage data.** Event logs, shell history, scheduled tasks and services, autoruns, recent files,
   browser history if relevant, user and group lists.
5. **Collect disk or snapshot** when needed (full image for serious cases, snapshot in cloud).
6. **Hash and store.** Compute SHA-256, write to the custody log, store read-only in access-controlled storage.
7. **Build the timeline.** Merge sources into one UTC table; mark pivots and gaps.
8. **Scope.** Search the same indicators and behaviors across other hosts and accounts (see `naki-sec-threat-hunting`).
9. **Report.** Findings, timeline, confidence, open questions, evidence list.

## Live collection examples (defensive, read-only)

Windows (PowerShell, run as administrator from a trusted share):

```powershell
$out = "E:\case-0142\$(hostname)"; New-Item -ItemType Directory -Force $out | Out-Null
Get-Process | Select-Object Id, ProcessName, Path, StartTime | Export-Csv "$out\processes.csv" -NoTypeInformation
Get-NetTCPConnection | Export-Csv "$out\netconn.csv" -NoTypeInformation
Get-ScheduledTask | Select-Object TaskName, TaskPath, State | Export-Csv "$out\tasks.csv" -NoTypeInformation
Get-CimInstance Win32_Service | Select-Object Name, PathName, StartMode, State | Export-Csv "$out\services.csv" -NoTypeInformation
wevtutil epl Security "$out\Security.evtx"
Get-ChildItem $out | Get-FileHash -Algorithm SHA256 | Export-Csv "$out\hashes.csv" -NoTypeInformation
```

Linux:

```bash
out=/mnt/evidence/case-0142/$(hostname); mkdir -p "$out"
ps auxww > "$out/ps.txt"; ss -tunap > "$out/ss.txt"; who -a > "$out/who.txt"
crontab -l > "$out/crontab_root.txt" 2>&1; ls -la /etc/cron.* > "$out/cron_dirs.txt"
journalctl --since "-7 days" -o short-iso-precise > "$out/journal.txt"
cp -a /var/log/auth.log* "$out/" 2>/dev/null
sha256sum "$out"/* > "$out/hashes.sha256"
```

Write output to external or network storage, never to the suspect disk if avoidable.

## Timeline building

Columns that work: `ts_utc, source, host, user, event, detail, artifact_ref, analyst_note`.

- Sources to merge: authentication logs, EDR or process events, web and proxy logs, DNS, cloud audit logs,
  file system timestamps, email gateway logs.
- Anchor on a confirmed malicious event, then expand backwards (initial access) and forwards (spread, impact).
- Mark each row as confirmed, likely or unverified.
- Note gaps (log rotation, missing sources) explicitly; a gap is a finding.
- Map key steps to MITRE ATT&CK techniques for the report.

## Chain of custody record

```markdown
| Item id | Description | SHA-256 | Collected by | Collected at (UTC) | Source | Storage location |
|---|---|---|---|---|---|---|
| E-001 | Memory image WS-17 | 9f2c...a1 | analyst.k | 2026-11-06 09:14 | WS-17 | evidence-share/case-0142/E-001 |

Transfers:
| Item id | From | To | When (UTC) | Purpose | Hash verified |
|---|---|---|---|---|---|
```

## Checklist

- [ ] Case opened; notes started with UTC times.
- [ ] Log retention checked and extended for involved sources.
- [ ] Volatile data collected before isolation or shutdown, where safe.
- [ ] Every artifact hashed and logged in the custody record.
- [ ] Evidence stored read-only with restricted access.
- [ ] Timeline merged in UTC with confidence per row and gaps marked.
- [ ] Scope checked on other hosts and accounts.
- [ ] Responder actions recorded so they are not confused with attacker actions.

## Common mistakes

- Rebooting or reimaging first, losing memory-only artifacts and the attacker's live connections.
- Running antivirus cleanup that deletes the sample before it is collected.
- Mixing local time and UTC in one timeline.
- Copying evidence without hashing, so integrity cannot be shown later.
- Logging in to the suspect host with a domain admin account, exposing a privileged credential.
- Forgetting cloud audit logs whose retention is short by default.

Follow the project rules skill if the project has one (for example `naki-myapp`).
