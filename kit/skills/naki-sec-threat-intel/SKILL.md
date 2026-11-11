---
name: naki-sec-threat-intel
description: Working with indicators of compromise and threat intelligence: indicator types, enrichment, confidence and ageing, STIX basics, and deciding when to block, alert or only watch. Use when handling IOC feeds, enriching an alert with intel, writing intel into a platform, or deciding whether an indicator justifies a block.
---

# Threat Intelligence and IOCs

Threat intelligence is only useful when it changes a decision: block, alert, hunt, or ignore. Treat every indicator as a
claim with a source, a confidence and an expiry, not as a fact.

## When to use

- Ingesting an IOC feed (IPs, domains, hashes, URLs) into a detection or incident platform.
- Enriching an alert or incident with reputation and context.
- Deciding whether an indicator is strong enough to block automatically.
- Writing up intel for an incident report or sharing it in STIX form.

## Core rules

1. Every indicator carries: value, type, source, first_seen, last_seen, confidence, TLP marking, and an expiry.
2. Indicators decay. An IP from a report six months ago is weak evidence today; hashes decay slowest, IPs fastest.
3. Never auto-block on a single low-confidence source. Blocking needs either high confidence or corroboration.
4. Check for shared infrastructure before blocking (CDNs, cloud ranges, public resolvers, mail providers, URL shorteners).
5. A match on an indicator is a lead, not a verdict. Triage the event around it (see `naki-sec-alert-triage`).
6. Respect TLP and feed licenses. Do not push TLP:AMBER or TLP:RED data into public tickets, repos or LLM prompts.
7. Record why an indicator was added and by whom, so it can be reviewed and removed.
8. Prefer behavior (TTPs mapped to MITRE ATT&CK) over atomic indicators for durable detections.

## Indicator types and value

The "pyramid" idea: the harder an indicator is for an adversary to change, the more valuable it is to detect.

| Type | Example field | Typical lifetime | Notes |
|---|---|---|---|
| File hash (SHA-256) | `file.hash.sha256` | months to years | Precise, trivially changed by recompiling. Prefer SHA-256 over MD5. |
| IP address | `source.ip` | hours to weeks | High false positive risk on shared hosting and cloud. |
| Domain | `dns.question.name` | days to months | Watch for newly registered domains and lookalikes. |
| URL | `url.full` | hours to days | Normalize before matching (case, trailing slash, encoding). |
| Email sender / subject | `email.from.address` | days | Useful for phishing clusters (see `naki-sec-phishing`). |
| JA3/JA4, certificate hash | `tls.client.ja3` | weeks to months | Good for tooling families, can collide with legit clients. |
| Artifacts (mutex, registry key, named pipe) | host telemetry | months | Tied to a tool family. |
| TTP (ATT&CK technique) | `threat.technique.id` | years | Most durable; needs a behavioral detection. |

## Confidence scoring

Use a simple 0 to 100 score and keep the inputs visible.

| Factor | Adds | Subtracts |
|---|---|---|
| Source reliability | Vetted vendor or own incident: +40 | Unknown paste or social post: +5 |
| Corroboration | Each independent source: +15 (cap +30) | |
| Own sighting | Seen in own telemetry with malicious context: +25 | |
| Age | | Older than type lifetime: -30 |
| Shared infrastructure | | CDN, cloud, sinkhole, public resolver: -40 |
| Allowlist hit | | Known good (top domains, own ranges): set to 0 |

Bands: 0 to 29 low, 30 to 69 medium, 70 to 100 high.

## Action decision table

| Confidence | Shared infra? | Asset criticality | Action |
|---|---|---|---|
| High | No | Any | Block at the edge plus alert on historical matches |
| High | Yes | Any | Alert only; block narrower (full URL, not domain or IP) |
| Medium | No | High | Alert with high priority, hunt last 30 days |
| Medium | No | Normal | Alert, no block |
| Low | Any | Any | Watchlist only (enrich, do not alert) |
| Any | Allowlisted | Any | Do not act; review the source quality |

Every block gets an expiry: IP 7 to 30 days, domain 30 to 90 days, hash 180 days or more. Expired entries are reviewed,
not silently extended.

## Workflow: ingesting a feed

1. Validate the format (CSV, JSON, STIX 2.1 bundle). Reject rows with invalid values (bad IP, domain without TLD).
2. Normalize: lowercase domains, strip `hxxp` and `[.]` defanging, canonicalize URLs, uppercase or lowercase hashes consistently.
3. Deduplicate against existing indicators; merge sources and update `last_seen` instead of inserting duplicates.
4. Filter against the allowlist (own domains and ranges, top popular domains, cloud provider ranges where relevant).
5. Score confidence and set expiry by type.
6. Decide the action from the table above.
7. Backfill: search the last N days of logs for matches and open alerts for hits.
8. Log the ingestion run: counts added, merged, rejected, expired.

## Workflow: enriching an alert

1. Extract observables from the alert: IPs, domains, URLs, hashes, user, host.
2. Look up each in internal intel first (past incidents, watchlists), then external reputation.
3. Add context: ASN and owner, geolocation, domain age and registrar, passive DNS, first seen in own logs.
4. Write enrichment as structured fields on the alert, with source and lookup time.
5. Do not let enrichment alone set the verdict. It adjusts priority; the event context decides.

## STIX 2.1 basics

STIX is a JSON format for sharing intel. The objects you will meet most:

- `indicator`: a detection pattern plus `valid_from`, `valid_until`, `confidence`.
- `observed-data`: something actually seen.
- `malware`, `tool`, `threat-actor`, `campaign`, `attack-pattern`: the context objects.
- `relationship`: links objects, for example indicator `indicates` malware.
- `marking-definition`: TLP markings.

Minimal indicator:

```json
{
  "type": "indicator",
  "spec_version": "2.1",
  "id": "indicator--3f1c2a9e-5b7d-4c11-9a0e-2d8f6b4e7a10",
  "created": "2026-11-01T10:00:00Z",
  "modified": "2026-11-01T10:00:00Z",
  "pattern": "[domain-name:value = 'login-update-portal.example']",
  "pattern_type": "stix",
  "valid_from": "2026-11-01T10:00:00Z",
  "valid_until": "2027-01-30T10:00:00Z",
  "confidence": 70,
  "labels": ["phishing"]
}
```

TAXII is the transport protocol for exchanging STIX bundles between servers.

## Data model suggestion

```text
indicator(id, type, value_normalized, confidence, tlp, first_seen, last_seen,
          expires_at, action, created_by, reason)
indicator_source(indicator_id, source_name, source_ref, seen_at)
indicator_match(indicator_id, event_id, matched_at, alert_id)
```

Index `(type, value_normalized)` unique. Run a daily job that expires indicators and reports what was removed.

## Common mistakes

- Blocking a cloud or CDN IP and breaking a business service.
- Matching defanged values (`evil[.]example`) that never appear in logs.
- No expiry, so the blocklist grows forever and false positives accumulate.
- Treating vendor "malicious" scores as ground truth without looking at the event.
- Putting raw intel reports with TLP:RED content into an LLM prompt or a public issue tracker.
- Hunting only forward: forgetting to backfill historical logs when a new indicator arrives.

## Intel note template

```markdown
## Intel note: <short title>
- Date / analyst:
- Source(s) and reliability:
- TLP:
- Indicators (type, value, confidence, expiry):
- Related ATT&CK techniques:
- Own sightings (where, when, count):
- Action taken (block / alert / watch) and why:
- Review date:
```

Follow the project rules skill if the project has one (for example `naki-myapp`).
