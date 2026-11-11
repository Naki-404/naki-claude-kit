---
name: naki-api-design
description: REST API design covering resource naming, HTTP methods and status codes, a consistent error format, pagination, filtering and sorting, versioning, and idempotency for retries. Use when designing new endpoints, reviewing an API contract or OpenAPI spec, or deciding how clients should page, filter, retry or handle errors.
---

# REST API Design

## When to use

- Designing endpoints before implementation, or reviewing a proposed contract.
- Picking status codes, an error body, pagination or a versioning scheme.
- Making write operations safe to retry.

Implementation details for Python services live in `naki-fastapi`; API security (object-level authz, rate limits) in `naki-sec-api-security`.

## Core rules

1. **Resources are plural nouns;** actions are HTTP methods. `/alerts`, `/alerts/{id}`, `/alerts/{id}/comments`. Avoid verbs in paths except for true operations that are not CRUD: `POST /alerts/{id}:escalate` or `POST /alerts/{id}/escalations`.
2. **Nest at most one level.** Beyond that, use top-level resources with filters: `/comments?alert_id=42`.
3. **Use lowercase, hyphenated paths and one JSON casing** (pick `snake_case` or `camelCase` and keep it everywhere, including query params and errors).
4. **Method semantics are a contract:**
   | Method | Safe | Idempotent | Typical success |
   |---|---|---|---|
   | GET | yes | yes | 200 |
   | POST | no | no (make it with a key) | 201 + `Location`, or 202 |
   | PUT (full replace) | no | yes | 200 or 204 |
   | PATCH (partial) | no | should be | 200 |
   | DELETE | no | yes | 204 (repeat delete: 204 or 404, pick one and document) |
5. **Status codes mean one thing each:**
   | Code | Use for |
   |---|---|
   | 400 | malformed request (bad JSON, bad query syntax) |
   | 401 | missing or invalid credentials |
   | 403 | authenticated but not allowed |
   | 404 | not found, or hidden for authz reasons |
   | 409 | state conflict (duplicate, version mismatch) |
   | 412 | `If-Match` precondition failed |
   | 422 | well-formed but fails validation |
   | 429 | rate limited, with `Retry-After` |
   | 500 | server bug; 502/503/504 for upstream or overload |
   Never return 200 with an error inside the body.
6. **One error format everywhere** (or RFC 9457 `application/problem+json`). Include a stable machine `code`, a human `message`, per-field `details`, and a `request_id`. Never include stack traces or SQL.
7. **Paginate every list endpoint from day one.** Cursor pagination for large or changing collections; offset only for small, stable sets. Enforce a max `limit`.
8. **Timestamps in ISO 8601 UTC** (`2026-11-08T09:30:00Z`); IDs as strings if they may exceed 2^53 or are UUIDs.
9. **Additive changes are free; breaking changes need a new version.** Adding optional fields or endpoints is fine. Removing, renaming, changing types or meaning is breaking.
10. **Writes that clients may retry must be idempotent.** Accept an `Idempotency-Key` header on POST and replay the stored response for repeats.

## Error body

```json
{
  "error": {
    "code": "validation_failed",
    "message": "Request has invalid fields.",
    "details": [{"field": "severity", "issue": "must be between 1 and 5"}],
    "request_id": "req_7f3a9c"
  }
}
```

## Pagination, filtering, sorting

```text
GET /alerts?status=open&severity_gte=3&sort=-created_at&limit=50&cursor=eyJpZCI6MTIzfQ
```

```json
{
  "data": [{"id": "a_123", "status": "open"}],
  "page": {"next_cursor": "eyJpZCI6MTczfQ", "limit": 50}
}
```

- Cursor is opaque to clients (base64 of the last sort key plus id); server decodes and runs `WHERE (created_at, id) < (:ts, :id)`.
- Sort by a unique tiebreaker (`created_at, id`) so pages never skip or repeat rows.
- Whitelist filterable and sortable fields; reject unknown ones with 400 instead of ignoring them.
- Range filters with suffixes (`_gte`, `_lt`) or bracket style; pick one convention.
- Return `total` only if it is cheap; counting large tables on every page is expensive.

## Versioning

- Prefer a major version in the path (`/v1/`) for public APIs; it is visible and cache friendly. Header versioning is fine for internal APIs if documented.
- Run old and new versions side by side; announce deprecation with a `Deprecation` and `Sunset` header and a date.
- Do not version for additive changes.

## Idempotency key flow

1. Client sends `POST /payments` with `Idempotency-Key: <uuid>`.
2. Server looks up the key scoped to the caller. If found and finished, return the stored status and body. If found and in progress, return 409.
3. If not found, store the key with a request hash, process, store the response, return it.
4. Same key with a different request body: 422.
5. Expire keys after a fixed window (for example 24 hours).

## Concurrency control

- Return `ETag` (version or hash) on GET; require `If-Match` on PUT/PATCH for resources edited by several users. Mismatch returns 412.
- Alternatively expose a `version` field and reject stale updates with 409.

## Long-running operations

- Return `202 Accepted` with `Location: /jobs/{id}`; the job resource reports `status`, `progress`, `result_url`, `error`.
- Do not hold a request open for minutes.

## Workflow

1. List the resources and their relationships; draw the URL tree.
2. For each operation, pick method, success code, error codes.
3. Define request and response schemas with constraints; write the OpenAPI spec or let the framework generate it and review it.
4. Decide pagination, filters, sorting per list endpoint.
5. Mark which writes need idempotency keys or ETags.
6. Review against the checklist; get the contract agreed before coding.

## Checklist

- [ ] Plural nouns, consistent casing, nesting at most one level.
- [ ] Correct status codes; no 200-with-error.
- [ ] Single error format with `code` and `request_id`.
- [ ] Every list endpoint paginated with a max limit and stable sort.
- [ ] Filters and sorts whitelisted.
- [ ] Retried writes idempotent; concurrent edits guarded.
- [ ] Breaking changes go into a new version; deprecations dated.
- [ ] Rate limits return 429 with `Retry-After`.

## Common mistakes

- `GET /getAlerts` or `POST /alerts/delete`.
- Returning 500 for validation errors because an exception escaped.
- Returning 403 for resources the caller should not know exist (leaks existence; use 404).
- Offset pagination on a table with frequent inserts, causing duplicates across pages.
- Silently ignoring unknown query parameters, so typos return unfiltered data.
- Changing a field type in place and breaking mobile clients that cannot update quickly.
- Different error shapes from the framework (422) and from app code.
