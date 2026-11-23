# TASK-07 §14.2 Step 3 — Database Lifecycle Wiring

| Field | Value |
|---|---|
| Step | §14.2 step 3 (wire database lifecycle) |
| Status | **IMPLEMENTED AND VERIFIED** |
| Date | 2026-11-23 |
| Authorization | Owner instruction “أصلح فجوة edit_static_route ثم واصل للخطوة 3” |
| Verification | `472 passed in 65.86s` (466 prior + 4 unit + 2 PostgreSQL integration tests); `ruff check` and `ruff format --check` clean across `app` and `tests` |
| Not included | `/api/v1` routers, revision guard, query projections, Ping adapter, error-handler mapping, OpenAPI snapshot |

## 1. Files changed/added

| File | Change |
|---|---|
| `app/main.py` | Added an `asynccontextmanager` lifespan that creates one engine and one session factory at startup, stores them on `app.state`, and disposes the pool on shutdown |
| `app/api/deps.py` | New `get_db_session(request)` yield-dependency |
| `tests/unit/test_db_lifecycle.py` | 4 tests: lifespan wiring, commit/close on success, rollback/close on error, missing-factory guard |
| `tests/integration/db/test_api_session_lifecycle.py` | 2 PostgreSQL tests: service work committed on success, rolled back on error |
| `docs/task07/STEP-03_db-lifecycle.md` | This record |

## 2. Design

- **One engine, one factory per process.** `create_db_engine()` and `create_session_factory()` from the existing `app/db/session.py` are called exactly once in the FastAPI lifespan. No per-request engine is created.
- **Request-scoped session with the existing transaction policy.** `get_db_session` wraps `session_scope(factory)`: commit once on success, roll back on any exception, always close. Service functions continue to accept a live `Session` and never commit independently.
- **No connection at startup.** `create_engine` is lazy (`pool_pre_ping=True`), so a down database does not prevent `/health`; the first DB-touching request will surface the failure for the step-8 `503 PERSISTENCE_UNAVAILABLE` mapping.
- **Guard against misconfiguration.** If `app.state.session_factory` is absent, the dependency raises a clear `RuntimeError` instead of silently creating an unbound session.

## 3. Boundaries and notes

- `app/main.py` still exposes only `/health`; no `/api/v1` router is mounted (that is step 4).
- Importing `app.main` now requires the `database` extra (`sqlalchemy`, `psycopg`), which is already a hard requirement of the TASK-06 persistence layer.
- The dependency is not yet referenced by any route; it is ready for step 4 routers to consume via `Depends(get_db_session)`.
- Frozen artifacts and original DOCX files untouched; no commit, push or PR action in this step.
