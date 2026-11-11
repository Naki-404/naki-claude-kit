---
name: naki-sec-web-appsec
description: Defensive web application security review against the OWASP Top 10: injection, auth and sessions, access control, SSRF, XSS, CSRF, file handling, headers and misconfiguration. Use when reviewing or writing web code that handles user input, auth, files or outbound requests, or when building detections for web attacks.
---

# Web Application Security

## When to use

- Reviewing a diff or module that touches user input, authentication, sessions, file upload, templates or outbound HTTP.
- Designing a new web feature and choosing safe defaults.
- Building signatures or correlations for web attacks seen in logs.
- Writing security regression tests for fixed vulnerabilities.

API-specific concerns (object-level authorization, rate limits, tokens) are in `naki-sec-api-security`. Pipeline checks (SAST, dependency scanning) are in `naki-sec-devsecops`. Follow the project rules skill if the project has one (for example `naki-myapp`).

## Core rules

1. Validate input at the boundary with an allowlist schema (type, length, format, range). Reject, do not repair.
2. Keep data and code separate: parameterized queries, safe template auto-escaping, argument arrays for subprocesses.
3. Deny by default. Every route declares who may call it; authorization is checked on the server for every request.
4. Encode output for its context (HTML body, attribute, JavaScript, URL, CSS).
5. Secrets come from the environment or a secret manager, never from source code or logs.
6. Fail closed: on error in an auth or authz check, deny.
7. Every fixed vulnerability gets a regression test.

## OWASP Top 10 (2021) review map

| Category | What to check | Fix pattern |
|---|---|---|
| A01 Broken Access Control | Object ids from the client used without owner check; admin routes guarded only in UI; CORS `*` with credentials | Server-side ownership check per object, central policy, deny by default |
| A02 Cryptographic Failures | Plain HTTP, weak hashing (MD5, SHA1 for passwords), hard-coded keys | TLS everywhere, Argon2id or bcrypt for passwords, managed keys |
| A03 Injection | String-built SQL, shell commands, LDAP, NoSQL queries, template rendering of user input | Parameters, ORM query builders, `subprocess` with list args and no shell, sandboxed templates |
| A04 Insecure Design | No rate limit on reset or login, business logic skips (negative quantities) | Threat model, abuse cases, limits |
| A05 Security Misconfiguration | Debug mode on, default credentials, verbose stack traces, directory listing | Hardened config per environment, generic error pages |
| A06 Vulnerable Components | Outdated packages with known CVEs | Lock files, scanning, update policy (see `naki-sec-vuln-management`) |
| A07 Identification and Auth Failures | No MFA option, weak reset flow, session fixation, unlimited attempts | Rotate session on login, lockout or backoff, secure reset tokens |
| A08 Software and Data Integrity | Unsigned updates, unsafe deserialization (`pickle`, YAML full loaders) | Signed artifacts, safe loaders, JSON with schemas |
| A09 Logging and Monitoring Failures | No auth event logs, no alerting | Log security events (see `naki-sec-log-analysis`) |
| A10 SSRF | Server fetches user-supplied URLs | Allowlist hosts, block private and link-local ranges after DNS resolution, no redirects |

## Safe and unsafe patterns

SQL (Python, SQLAlchemy 2):

```python
# Unsafe: user input concatenated into SQL
db.execute(text(f"SELECT * FROM users WHERE email = '{email}'"))

# Safe: bound parameter
db.execute(text("SELECT * FROM users WHERE email = :email"), {"email": email})
```

Subprocess:

```python
# Unsafe: shell=True with user data
subprocess.run(f"convert {name} out.png", shell=True)

# Safe: argument list, validated name, no shell
if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}\.png", name):
    raise ValueError("bad file name")
subprocess.run(["convert", str(UPLOAD_DIR / name), "out.png"], check=True)
```

SSRF guard idea:

```python
import ipaddress, socket
from urllib.parse import urlparse

ALLOWED_HOSTS = {"api.partner.example"}

def check_url(url: str) -> None:
    parts = urlparse(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise ValueError("host not allowed")
    for info in socket.getaddrinfo(parts.hostname, 443):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("internal address")
```

Also disable redirects on the HTTP client or re-check each hop, and pin the resolved IP for the actual request to avoid DNS rebinding.

## Authentication and sessions

- Session cookies: `HttpOnly`, `Secure`, `SameSite=Lax` or `Strict`, short idle timeout, new session id after login and privilege change.
- Passwords: Argon2id or bcrypt, minimum length check, breached password check if possible, no maximum below 64 characters.
- Reset tokens: random 128 bits or more, single use, short expiry, stored hashed.
- Login responses do not reveal whether the account exists.
- CSRF: token per session or per form for cookie-authenticated state-changing requests; `SameSite` is a second layer, not the only one.

## XSS

- Use framework auto-escaping; never mark user input as safe HTML.
- In React, avoid `dangerouslySetInnerHTML`; if rich text is required, sanitize with an allowlist sanitizer on the server.
- Set a Content Security Policy without `unsafe-inline` for scripts where possible.
- Validate URLs used in `href` and `src` (block `javascript:` scheme).

## File upload and download

- Allowlist extensions and verify content type by magic bytes, not the client header.
- Generate server-side file names; store outside the web root; serve with `Content-Disposition: attachment` for untrusted types.
- Limit size and count; scan if the files are shared with others.
- Resolve download paths and confirm they stay inside the storage directory (path traversal, CWE-22).
- Do not parse archives or XML from users without limits (zip bombs, XXE: disable external entities).

## Security headers baseline

| Header | Value idea |
|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |
| `Content-Security-Policy` | `default-src 'self'; frame-ancestors 'none'` and tighten from there |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | Disable features you do not use |

## Review workflow

1. List entry points: routes, forms, file uploads, webhooks, background jobs that consume user data.
2. For each, trace input to sinks: database, shell, file system, template, outbound HTTP, redirect, deserializer.
3. Check authn and authz on each route; compare with the intended role matrix.
4. Grep for risky sinks: `shell=True`, `eval(`, `exec(`, `pickle.loads`, `yaml.load(`, `text(f"`, `innerHTML`, `dangerouslySetInnerHTML`, `verify=False`, `DEBUG = True`.
5. Check configuration: debug flags, CORS, cookies, headers, error pages.
6. Report findings with severity, location, evidence, fix, and a test idea.

## Finding template

```text
[HIGH] A01 Broken Access Control: invoice download lacks owner check
Where: app/routes/invoices.py:42 get_invoice()
Evidence: invoice loaded by id from path; no comparison with current_user.org_id
Impact: any authenticated user can read other organizations' invoices
Fix: filter query by org_id from the session; return 404 when not found
Test: user from org B requests org A invoice id, expects 404
```

## Common mistakes

- Relying on hidden form fields or disabled buttons for authorization.
- Escaping on input instead of encoding on output for the right context.
- Blocking `169.254.169.254` as a string but not decimal, IPv6 or redirect variants (check resolved addresses).
- Logging full request bodies that contain passwords or tokens.
- Fixing the reported endpoint and missing the same pattern in three others; grep for siblings.
