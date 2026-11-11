---
name: naki-sec-api-security
description: API security against the OWASP API Security Top 10: authentication, object and function level authorization, property exposure, rate limits, input validation, tokens and secrets, inventory and monitoring. Use when designing, reviewing or testing REST or webhook APIs, adding auth to endpoints, or detecting API abuse in logs.
---

# API Security

## When to use

- Designing or reviewing API endpoints, especially multi-tenant ones.
- Adding authentication, API keys, OAuth scopes or webhook verification.
- Investigating API abuse: enumeration, scraping, credential stuffing, token misuse.
- Writing authorization tests.

General web issues (injection, XSS, SSRF details) are in `naki-sec-web-appsec`. Endpoint shape, status codes and pagination are in `naki-api-design`. FastAPI wiring is in `naki-fastapi`.

## Core rules

1. Every endpoint is authenticated unless it is explicitly listed as public.
2. Authorization happens on the server for every object, every request. Knowing an id is not permission.
3. Return only the fields the caller may see. Serialize through explicit response schemas, never raw ORM objects.
4. Accept only the fields the caller may set. Explicit input schemas, no mass assignment.
5. Limit everything: request rate, page size, body size, query complexity, upload size, time.
6. Tokens are short-lived and scoped; secrets are hashed at rest and never logged.
7. Keep an inventory of all endpoints and versions; retire old ones.

## OWASP API Security Top 10 (2023) map

| Id | Risk | Check | Fix |
|---|---|---|---|
| API1 | Broken Object Level Authorization (BOLA) | Can user A read or change user B's object by changing the id? | Scope every query by tenant and owner from the token |
| API2 | Broken Authentication | Weak token validation, no expiry, keys in URLs | Validate signature, `exp`, `aud`, `iss`; keys in headers |
| API3 | Broken Object Property Level Authorization | Response leaks internal fields; client can set `role` or `is_admin` | Separate read and write schemas per role |
| API4 | Unrestricted Resource Consumption | No rate or size limits, unbounded `limit` parameter | Rate limits per key and IP, max page size, timeouts |
| API5 | Broken Function Level Authorization | Normal user can call admin endpoints | Role checks per route, deny by default |
| API6 | Unrestricted Access to Sensitive Business Flows | Bots buying stock, mass sign-ups, coupon abuse | Flow-specific limits, anomaly detection, step-up checks |
| API7 | Server Side Request Forgery | API fetches URLs given by the client | Allowlist and resolved address checks |
| API8 | Security Misconfiguration | Verbose errors, open CORS, debug endpoints, missing TLS | Hardened config, generic errors |
| API9 | Improper Inventory Management | Old `/v1` still live without auth fixes, staging exposed | Inventory, deprecation dates, gateway enforcement |
| API10 | Unsafe Consumption of APIs | Trusting third-party API responses blindly | Validate and limit third-party data like user input |

## BOLA: the most common bug

```python
# Unsafe: trusts the id, ignores tenant
@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: int, db: Session = Depends(get_db)):
    return db.get(Incident, incident_id)

# Safe: scoped by tenant from the verified token, 404 on miss
@router.get("/incidents/{incident_id}", response_model=IncidentOut)
async def get_incident(incident_id: int, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    stmt = select(Incident).where(Incident.id == incident_id,
                                  Incident.tenant_id == user.tenant_id)
    incident = db.scalars(stmt).first()
    if incident is None:
        raise HTTPException(status_code=404)
    return incident
```

Return 404 (not 403) for objects in other tenants so ids cannot be confirmed. Random ids (UUIDs) reduce enumeration but do not replace the check.

## Authentication choices

| Caller | Mechanism | Notes |
|---|---|---|
| Browser user | Session cookie or OAuth 2.0 / OIDC with PKCE | Cookies: HttpOnly, Secure, SameSite; CSRF protection |
| Service to service | OAuth client credentials or mTLS | Short-lived tokens, scoped audiences |
| Third-party integration | API key per client, scoped | Store hash only, show once, allow rotation, record last used |
| Webhook receiver | HMAC signature over body plus timestamp | Constant-time compare, reject old timestamps (replay) |

JWT checklist: verify signature with the expected algorithm only (reject `none` and unexpected algorithms), check `exp`, `nbf`, `iss`, `aud`, keep lifetimes short (minutes), use refresh tokens with rotation and revocation, do not put secrets or personal data in the payload.

Webhook verification:

```python
import hashlib, hmac, time

def verify(body: bytes, ts: str, sig: str, secret: bytes) -> bool:
    if abs(time.time() - int(ts)) > 300:
        return False
    expected = hmac.new(secret, ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
```

## Rate limiting and abuse controls

- Limit per API key or user and per IP; stricter on login, reset, sign-up, search and export.
- Return `429` with `Retry-After`.
- Cap `limit` / `page_size` (for example 100) and reject larger values.
- Set body size limits and request timeouts at the gateway and in the app.
- For expensive queries (GraphQL, search), limit depth and complexity.

## Detecting API abuse in logs

| Pattern | Shape | ATT&CK / note |
|---|---|---|
| Object enumeration (BOLA probing) | One caller, sequential ids, many 404 or 403 then some 200 | Often precedes data theft (T1530-like collection) |
| Credential stuffing | Many accounts, many IPs, high 401 ratio on login | T1110.004 |
| Token reuse from new location | Same token or key from two ASNs or countries | T1550.001 Application Access Token |
| Scraping | Steady high request rate, full pagination walks, uniform user agent | Business flow abuse (API6) |
| Mass export | Unusual volume of list or export calls by one key | Possible exfiltration (T1567 if to external storage) |
| Old version use | Traffic to deprecated endpoints | Inventory gap (API9) |

Log per request: timestamp, request id, caller id (user or key id, never the key), tenant, method, route template, object id, status, latency, bytes, source IP, user agent.

## Testing authorization

- Build a matrix: roles x endpoints x expected result. Test it automatically.
- For each object endpoint, test: owner (200), same-tenant other user (as designed), other tenant (404), anonymous (401).
- Test mass assignment: send `role`, `tenant_id`, `is_admin` in the body and confirm they are ignored or rejected.
- Test limits: oversized `limit`, oversized body, rapid requests return 429.

```python
def test_other_tenant_cannot_read_incident(client, token_tenant_b, incident_tenant_a):
    r = client.get(f"/incidents/{incident_tenant_a.id}",
                   headers={"Authorization": f"Bearer {token_tenant_b}"})
    assert r.status_code == 404
```

## Checklist

- [ ] Every route has an explicit auth dependency or is on the public allowlist
- [ ] Every object query is scoped by tenant and owner
- [ ] Separate input and output schemas; no internal fields exposed
- [ ] Rate limits, page size caps, body size limits, timeouts
- [ ] Tokens validated fully; API keys hashed; no secrets in URLs or logs
- [ ] Webhooks verified with HMAC and timestamp
- [ ] Authorization matrix tests in CI
- [ ] Endpoint inventory current; deprecated versions have a removal date

## Common mistakes

- Checking authorization in the list endpoint but not in get, update or delete.
- Trusting `tenant_id` from the request body or a header instead of the verified token.
- Returning the full user object including password hash or internal flags.
- Rate limiting only by IP, which fails against distributed attacks and punishes shared NAT.
- Putting API keys in query strings, where they end up in proxy and server logs.
