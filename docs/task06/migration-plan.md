# Migration Plan — TASK-06

## Tooling

- Alembic 1.20 (`alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`).
- `SYNTRA_DATABASE_URL` selects the target database (default
  `postgresql+psycopg://postgres@localhost:5432/syntra`).
- `Base.metadata` is the single source of truth for tables, columns, keys and
  enum types; `migrations/env.py` imports `app.db.models` so it is complete.

## Revisions

| Revision | Description |
|---|---|
| `0001_initial` | Creates all 16 tables, 10 enum types, indexes, constraints, triggers, views and seeds the default retention policy. |

`upgrade()` calls `Base.metadata.create_all(bind)` then executes
`app/db/sql/constraints.sql`.  `downgrade()` drops the views, tables and enum
types in reverse order.

## Applying

```bash
# against a running PostgreSQL 13+
export SYNTRA_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/syntra
alembic upgrade head
```

## Local development without Alembic

```python
from app.db.schema import create_schema, drop_schema

create_schema(engine)  # idempotent-ish: drop first if re-running
```

## Runtime schema bootstrap

`app/db/schema.py::create_schema(bind)` is the same code path used by the
migration and by the integration test fixtures, so DDL drift between migration
and application cannot occur.

## Backwards compatibility

- No previous TASK-06 schema exists in this repository (the earlier
  `syntra database` SQL was rejected as unexecutable), so `0001_initial` is the
  first and only revision.
- Future revisions must be normal column-level Alembic operations; do not edit
  `0001_initial`.
