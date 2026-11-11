---
description: Defensive security audit of the project or a path: secrets, dependencies, authz, injection, SSRF, config, logs; findings with fixes
argument-hint: [path, default whole project]
---

# /naki-security-audit

Audit the project (or the path in `$ARGUMENTS`) for security weaknesses and list concrete fixes. Defensive only.
Do not edit code in this command and do not scan hosts you do not own.

Read the project rules skill if present (for example `naki-myapp`).

## 1. Map the system

- Stack, entry points (HTTP routes, CLIs, workers, webhooks), data stores, outbound integrations.
- Which parts are internet-facing, which handle personal or sensitive data.
- If a Code Map exists, `codemap_search` for "auth", "login", "token", "upload", "request" speeds this up.

## 2. Audit areas

Run the `naki-security-reviewer` agent on the main modules (several in parallel for large projects), and cover each
area below. Use `naki-sec-web-appsec`, `naki-sec-api-security` and `naki-sec-devsecops` as checklists.

1. **Secrets**: keys, tokens and passwords in code, configs, tests, notebooks, Docker files and git history
   (`gitleaks detect` or `git log -p` search if no scanner). Check `.gitignore` covers `.env` files.
2. **Dependencies**: `pip-audit`, `npm audit --omit=dev`, or the project's scanner. Prioritize by exploitability
   and exposure (`naki-sec-vuln-management`). Note unpinned or abandoned packages.
3. **Authentication and authorization**: password hashing, token validation, session handling; every route and
   object access checked for the caller's rights; tenant isolation; admin endpoints.
4. **Injection**: SQL built from strings, shell calls, template rendering, path traversal, unsafe deserialization.
5. **SSRF**: server-side fetches of user-supplied URLs, redirects, internal metadata addresses, missing allowlists
   and timeouts.
6. **Configuration**: debug mode, CORS, cookie flags, security headers, TLS settings, default credentials, container
   running as root, exposed ports (`naki-sec-cloud-containers`, `naki-docker-deploy`).
7. **Logging and monitoring**: secrets or personal data in logs, missing audit logs for auth and admin actions,
   errors that leak stack traces to clients.
8. **LLM features** if present: prompt injection into tools, output validation (`naki-sec-llm-security`).

## 3. Rules

- Never print a found secret value. Give its location and say it must be rotated.
- Rank findings by severity: Critical, High, Medium, Low. Add CWE ids where clear.
- If an area has no findings, say so and what was checked.

## 4. Report

```
## Security audit: <project or path>
Exposure: ...
Summary: N Critical, N High, N Medium, N Low

| # | Severity | Area | Location | Finding | Fix |
|---|---|---|---|---|---|

### Details
#### 1. [Critical] <title> (CWE-...)
- Location: file:line
- Abuse scenario: ...
- Fix: ...

### Areas with no findings
- ...

### Fix plan
1. Immediate (Critical/High): ...
2. Next sprint: ...
3. Hardening backlog: ...
```

Offer to implement fixes afterwards. If the user agrees, change code in small steps, run the project's tests and
linters after changes, and commit only when the user asks.
