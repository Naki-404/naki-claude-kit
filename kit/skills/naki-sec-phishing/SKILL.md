---
name: naki-sec-phishing
description: Phishing analysis and defense: reading email headers and authentication results (SPF, DKIM, DMARC), safe triage of links and attachments, handling user reports, scoping and purging a campaign, takedown requests and awareness. Use when a suspicious email is reported, building a phishing triage workflow, or hardening mail authentication.
---

# Phishing Analysis and Defense

Phishing triage answers three questions fast: is it malicious, who else received it, and did anyone interact with it.
Analyze safely, never from a normal workstation session, and never by clicking.

## When to use

- A user reports a suspicious email, SMS or chat message.
- A mail gateway or detection rule flags a message.
- A campaign hits many mailboxes and needs scoping and removal.
- Setting up SPF, DKIM and DMARC, or a report button and triage workflow.

## Core rules

1. Never open links or attachments on a normal workstation. Use passive lookups first, then an isolated sandbox.
2. Work from the original message (`.eml` or `.msg` with full headers), not a forwarded copy or screenshot.
3. Defang indicators in notes and tickets (`hxxps://example[.]com`) so nobody clicks by accident.
4. The `From:` display name and address are trivially forged. Trust only authentication results from your own
   receiving server.
5. Scope before you close: one report usually means more recipients.
6. If someone entered credentials or ran an attachment, it is an incident, not a phishing ticket
   (see `naki-sec-incident-response`).
7. Thank the reporter and tell them the outcome. Reporting rate matters more than click rate.
8. Do not submit internal or sensitive attachments to public scanning services; use private sandboxes.

## Header analysis

Read `Received:` headers from the bottom (origin) to the top (your server). Key fields:

| Header | Check |
|---|---|
| `Authentication-Results` (added by your server) | `spf=`, `dkim=`, `dmarc=` results and the domains they apply to |
| `From` vs `Return-Path` (envelope sender) | Mismatch is common in bulk mail but suspicious with lookalike domains |
| `Reply-To` | Different domain from `From` is a classic signal for payment fraud |
| `Received` chain | First external hop: IP, rDNS, ASN; unexpected countries or residential ranges |
| `Message-ID` | Domain inconsistent with the sender system |
| `Date` | Far off from received time |
| `X-Mailer` / `User-Agent` | Unusual mailers for that sender |

Authentication meaning:

| Result | Meaning | Caution |
|---|---|---|
| SPF pass | Sending IP allowed for the envelope domain | Envelope domain may differ from visible `From` |
| DKIM pass | Message signed by `d=` domain and not altered | `d=` may be an unrelated bulk sender |
| DMARC pass | SPF or DKIM passed and aligned with visible `From` domain | Lookalike domains can pass DMARC for themselves |
| DMARC fail with `p=reject` | Should have been rejected | Check why it was delivered (allowlist, forwarding) |

## Verdict decision table

| Signals | Verdict | Action |
|---|---|---|
| Auth aligned with a known legitimate sender, expected content | Benign or spam | Close, tell reporter, tune filters if spam |
| Lookalike or newly registered domain, credential form or urgent payment request | Malicious | Purge, block, scope, check clicks |
| Attachment with macros, script, archive with executable, HTML smuggling | Malicious | Purge, block hash and sender, sandbox in isolation |
| Compromised legitimate sender (auth passes, odd content) | Malicious | Purge, notify the sender organization |
| Internal phishing simulation | Simulation | Mark, thank reporter |
| Unclear | Suspicious | Hold or quarantine, escalate for sandbox analysis |

## Workflow

1. **Receive.** Get the original message with headers. Create a ticket; note reporter and time.
2. **Extract.** Sender addresses, reply-to, sending IPs, subject, URLs (including in HTML and QR codes), attachment
   names and SHA-256 hashes.
3. **Passive enrichment.** Domain age and registrar, URL and hash reputation, sender IP reputation, prior sightings in
   your own mail logs (see `naki-sec-threat-intel`).
4. **Safe dynamic analysis** only if needed: isolated sandbox or a URL detonation service, never a user machine.
5. **Verdict.** Use the table above; record the evidence that decided it.
6. **Scope.** Search mail logs for the same sender, subject, URL or hash. List recipients and delivery status.
7. **Interaction check.** Proxy and DNS logs for clicks on the URL; sign-in logs for new sessions or MFA prompts after
   the click; EDR for attachment execution.
8. **Contain.** Purge the message from all mailboxes, block sender domain, URLs and hashes at gateway and proxy.
   For users who submitted credentials: reset password, revoke sessions and tokens, review MFA methods and mailbox rules.
9. **Takedown.** Report the phishing site to the hosting provider and registrar abuse contacts, and to browser safe
   browsing services. Keep evidence (screenshot from sandbox, URL, timestamps).
10. **Close and feed back.** Tell the reporter, add detections for the pattern, update awareness material.

## Signs worth a detection rule

- New inbox rule forwarding or deleting mail right after a suspicious sign-in (ATT&CK T1114.003, T1564.008).
- Sign-in from a new country or hosting ASN within minutes of a phishing click.
- Many users receiving the same external URL in a short window.
- Display name matches an executive but the address is external.
- OAuth consent grants to unknown applications after an email lure (T1528).

See `naki-sec-detection-engineering` for writing and testing these rules.

## Mail authentication hardening

1. Publish SPF listing only real senders; end with `-all` once complete.
2. Sign all outbound mail with DKIM (2048-bit keys), including third-party senders.
3. Publish DMARC with reporting: start `p=none`, review aggregate reports, move to `quarantine`, then `reject`.
4. Cover parked and unused domains with `v=spf1 -all` and DMARC `p=reject`.
5. Tag external mail in the client and warn on lookalike domains of your own.

```text
_dmarc.example.com.  TXT  "v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@example.com; adkim=s; aspf=s"
```

## Report template

```markdown
## Phishing case <id>
- Reported by / at (UTC):
- Subject / sender / reply-to:
- Auth results: SPF / DKIM / DMARC (aligned?):
- Indicators (defanged): URLs, domains, IPs, hashes
- Verdict and deciding evidence:
- Recipients (count) / purged (count):
- Interactions: clicked (users), credentials entered (users), attachment run (hosts)
- Containment: blocks, resets, session revocations
- Takedown requests sent (to whom, when):
- Follow-ups: detections, awareness, filter tuning
```

## Common mistakes

- Clicking a link "just to see" from an analyst workstation.
- Trusting a green SPF result without checking which domain it applied to.
- Closing a single report without searching for other recipients.
- Resetting a password but leaving active sessions, OAuth grants and malicious inbox rules in place.
- Blaming users who clicked, which lowers future reporting.

Follow the project rules skill if the project has one (for example `naki-myapp`).
