---
name: naki-postgres
description: PostgreSQL with SQLAlchemy 2, covering schema design, indexes, query tuning with EXPLAIN, transactions and locking, Alembic migrations and zero-downtime schema changes. Use when designing tables, writing or reviewing queries and ORM code, a query is slow, or a migration must run on a live database.
---

# PostgreSQL and SQLAlchemy 2

## When to use

- Designing tables, constraints and indexes.
- Writing SQLAlchemy 2 models and queries, sync or async.
- A query is slow, locks pile up, or connections run out.
- Writing an Alembic migration, especially against a table with live traffic.

For destructive data changes also apply `naki-safety`. Follow the project rules skill if the project has one (for example `naki-myapp`).

## Schema rules

1. **Primary keys:** `bigint generated always as identity` or UUID (v7 if available, for index locality). Do not expose sequential ids publicly if enumeration matters.
2. **Types:** `timestamptz` (never `timestamp` without zone), `text` with a `CHECK` on length instead of `varchar(n)` when limits may change, `numeric` for money, `jsonb` (not `json`), `boolean not null default false`.
3. **Constraints are the last line of defense:** `NOT NULL` by default, `UNIQUE`, `CHECK`, foreign keys with an explicit `ON DELETE` choice.
4. **Index every foreign key** used in joins or cascades; Postgres does not do it automatically.
5. **Name constraints and indexes** via a naming convention in SQLAlchemy `MetaData` so Alembic diffs are stable.
6. **jsonb for genuinely variable data,** not to avoid modelling. Query-hot keys become real columns.
7. **Soft delete only if you need it;** if you do, add partial indexes `WHERE deleted_at IS NULL`.

## Index rules

| Query pattern | Index |
|---|---|
| equality and range on one column | B-tree |
| `WHERE a = ? AND b > ? ORDER BY b` | composite `(a, b)`, equality columns first |
| subset of rows (open items) | partial `WHERE status = 'open'` |
| `lower(email) = ?` | expression index on `lower(email)` |
| jsonb containment `@>` | GIN |
| full-text, trigram `ILIKE '%x%'` | GIN with `tsvector` or `pg_trgm` |
| huge append-only time series | BRIN on the timestamp |

- Every index costs writes and disk. Remove unused ones (`pg_stat_user_indexes.idx_scan = 0` over a long window).
- Covering index with `INCLUDE (...)` for index-only scans on hot reads.

## Query tuning workflow

1. Get the real query (enable `echo` or `log_min_duration_statement`) and real parameters.
2. Run `EXPLAIN (ANALYZE, BUFFERS)` on a production-like dataset. Never trust plans from a 100-row dev table.
3. Look for: `Seq Scan` on large tables with selective filters, row estimate far from actual (stale stats: `ANALYZE`), nested loops over many rows, sorts spilling to disk, high `shared read`.
4. Fix the cheapest cause: add or adjust index, rewrite the predicate to be sargable, remove N+1, paginate by keyset.
5. Re-run `EXPLAIN ANALYZE` and compare timings. Use `pg_stat_statements` to find top total-time queries.

## SQLAlchemy 2 rules

1. Use the 2.0 style: `select()`, `session.execute()`, `session.scalars()`, `Mapped[...]` and `mapped_column`.
2. **One session per unit of work** (request, job). Never share a session across threads or tasks.
3. **Avoid N+1:** load relationships explicitly with `selectinload` (collections) or `joinedload` (many-to-one). In async code lazy loading raises; set `lazy="raise"` on relationships to catch it in sync code too.
4. Use bound parameters only. Never format user input into SQL strings, including `text()`.
5. Set pool size and `pool_pre_ping=True`; total connections across all app instances must stay under `max_connections` (use PgBouncer if many workers).
6. Keep transactions short; no network calls to other services while holding a transaction.

```python
from datetime import datetime
from sqlalchemy import ForeignKey, Index, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

class Base(DeclarativeBase):
    pass

class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    opened_at: Mapped[datetime]
    alerts: Mapped[list["Alert"]] = relationship(back_populates="incident", lazy="raise")
    __table_args__ = (Index("ix_incidents_open", "opened_at", postgresql_where="status = 'open'"),)

async def open_incidents(session: AsyncSession, limit: int) -> list[Incident]:
    stmt = (
        select(Incident)
        .where(Incident.status == "open")
        .order_by(Incident.opened_at.desc(), Incident.id.desc())
        .limit(limit)
        .options(selectinload(Incident.alerts))
    )
    return list((await session.scalars(stmt)).all())
```

## Transactions and locking

- Default `READ COMMITTED` is fine for most work. Use `SELECT ... FOR UPDATE` to lock rows you will modify based on what you read.
- For queues: `FOR UPDATE SKIP LOCKED` lets several workers claim jobs without blocking each other.
- Upserts: `INSERT ... ON CONFLICT (key) DO UPDATE` instead of read-then-insert races.
- Set `lock_timeout` and `statement_timeout` for app roles so one bad query cannot stall everything.
- Deadlocks come from locking rows in different orders; lock in a consistent order (sort by id).

## Alembic and zero-downtime changes

Always review autogenerated migrations; autogenerate misses renames (it emits drop plus add) and some type changes.

Expand and contract for breaking changes:

1. **Expand:** add new column nullable (or with a constant default, which is instant on PG 11+), new table, or new index `CONCURRENTLY`.
2. Deploy code that writes both old and new.
3. **Backfill** in batches (for example 5k rows per transaction) outside the migration, or in a separate data migration with progress logging.
4. Deploy code that reads new.
5. **Contract:** drop old column in a later release.

Dangerous operations on large live tables:

| Operation | Safer approach |
|---|---|
| `CREATE INDEX` | `CREATE INDEX CONCURRENTLY` (Alembic: `postgresql_concurrently=True` inside `with op.get_context().autocommit_block():`) |
| add `NOT NULL` | add `CHECK (col IS NOT NULL) NOT VALID`, `VALIDATE CONSTRAINT`, then set NOT NULL |
| add foreign key | add with `NOT VALID`, then `VALIDATE CONSTRAINT` |
| rename column | expand and contract, never in-place with old code running |
| change column type | new column plus backfill, not `ALTER TYPE` rewriting the table |

- Set `SET lock_timeout = '5s'` in migrations so they fail fast instead of queueing behind long transactions.
- Every migration has a working `downgrade()` or a written note why it cannot.
- Test migrations up, down and up again on a copy of realistic data.

## Checklist

- [ ] `timestamptz`, `NOT NULL` defaults, named constraints, indexed foreign keys.
- [ ] Queries parameterized; no f-strings in SQL.
- [ ] No N+1; relationships loaded explicitly.
- [ ] Slow queries checked with `EXPLAIN (ANALYZE, BUFFERS)` on realistic data.
- [ ] Transactions short; timeouts set.
- [ ] Migration reviewed, reversible, uses `CONCURRENTLY` / `NOT VALID` where needed.
- [ ] Backfills batched and resumable.

## Common mistakes

- `OFFSET 100000` pagination; use keyset on an indexed sort key.
- `WHERE date(created_at) = ?` defeating the index; use a range on the raw column.
- `LIKE '%term%'` without trigram index.
- Forgetting `await session.commit()`, or committing inside a loop per row.
- Running `alembic revision --autogenerate` and committing it unread.
- Holding a transaction open while calling an external API.
- Storing timestamps in local time.
