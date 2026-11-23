# TASK-07 §14.2 Step 6 — Query Projections

| Field | Value |
|---|---|
| Step | §14.2 step 6 (add query projections) |
| Status | **IMPLEMENTED AND VERIFIED** |
| Date | 2026-11-23 |
| Authorization | Owner instruction “انتقل للخطوة 6: query projections (موصى به)” |
| Contract basis | §6 catalogue, §7.1 (list parameters), §14.2 step 6, decision D7-07, acceptance §13 (stable ordering, bounded pagination, no child leakage) |
| Verification | `522 passed in 99.66s` (510 prior + 1 unit + 11 PostgreSQL integration tests); `ruff check` and `ruff format --check` clean across `app` and `tests` |
| Not included | Ping adapter (step 7), persistence-error mapping (step 8), OpenAPI snapshot artifact (step 9) |

## 1. Files added/changed

| File | Change |
|---|---|
| `app/modules/projects/service.py` | New read-only `list_projects(session, *, limit=50, offset=0)` ordered by `(created_at, project_id)`; added to `__all__` |
| `app/api/v1/schemas.py` | `ProjectSummary` DTO + `ProjectListEnvelope`, `CollectionEnvelope`, `DeviceEnvelope` |
| `app/api/v1/queries.py` | New router: 8 GET operations + `ResourceNotFoundError` (404 `NOT_FOUND`) for child lookups |
| `app/api/v1/router.py` | Queries router included |
| `tests/unit/test_api_routes.py` | Query routes asserted mounted; only Ping remains deferred; operation count now 27 |
| `tests/integration/db/test_api_queries.py` | 11 PostgreSQL tests |
| `docs/task07/STEP-06_query-projections.md` | This record |

## 2. Mounted read surface (8 new operations, 27 total)

| Operation | Path | Source |
|---|---|---|
| `listProjects` | `GET /projects` | New bounded `list_projects` query (D7-07) |
| `listRevisions` | `GET /projects/{id}/revisions` | `open_project` projection |
| `listCheckpoints` | `GET /projects/{id}/checkpoints` | `open_project` projection (`[]` when absent) |
| `listDevices` | `GET /projects/{id}/devices` | `open_project` projection |
| `getDevice` | `GET /projects/{id}/devices/{device_id}` | Canonical device object lookup |
| `listInterfaces` | `GET /projects/{id}/interfaces` | `open_project` projection |
| `listConnections` | `GET /projects/{id}/connections` | `open_project` projection |
| `listStaticRoutes` | `GET /projects/{id}/static-routes` | `open_project` projection |

## 3. Contract behavior implemented

1. **Canonical consistency:** every project-scoped read reuses `open_project`, so each collection is observed at one committed revision (SHARE lock) and equals the corresponding array of `GET /projects/{id}` byte-for-byte (asserted by tests).
2. **ETag on project reads:** all project-scoped reads return the current `ETag`; the cross-project list has no single-project ETag.
3. **Bounded pagination (§7.1):** `limit` default 50, range 1–100; `offset` default 0, ≥ 0; out-of-range values are 422 through the existing validation envelope. Ordering is stable `(created_at, project_id)` and repeatable (asserted).
4. **No child leakage:** `ProjectSummary` carries only identity, text, the two revisions and timestamps — no child collections and no internal sequence counters.
5. **Full revision array:** `listRevisions` returns the complete ordered audit array with no pagination or selection marker, consistent with the V1 full-array policy.
6. **Child lookup classification (§9.2):** an unknown device in an existing project returns 404 `NOT_FOUND` via a typed `AppError` (no message-string matching, no other project's data). Unknown *projects* still surface `ProjectNotFoundError` as 500 until step 8.
7. Reads never require `If-Match` and never mutate; no lifecycle rule was altered (D7-07).

## 4. Deliberate implementation choices

- List responses use `data: [ProjectSummary]` directly (no wrapper object, no total count): the draft specifies summaries plus limit/offset inputs but no total-count contract, and a count query would add an unrequested read. Recorded here for step-9 OpenAPI review.
- `list_projects` lives in the service layer (not the router) so the read stays reusable and the router remains a thin translation layer; it applies no lock because it is a plain bounded read.
- The URL segment is `/static-routes` while the canonical document key stays `static_routes`; projections map between the two without renaming the frozen document field.

## 5. Verification detail

- Unit (1 new + updated): all 8 query routes mounted, Ping still absent, 27 unique operation IDs incl. `listProjects`/`getDevice`.
- Integration (11, PostgreSQL): empty list; summaries without children; bounded stable pagination; 422 for limit 0/101 and offset −1; all five collections equal the canonical arrays with matching ETags; full ordered revision array 1–6; checkpoint list empty→saved; single-device read equals canonical object; unknown device → 404 envelope with request ID.
- Full suite: **522 passed in 99.66s**; no pre-existing test regressed.
- Frozen artifacts and original DOCX files untouched; no commit, push or PR action in this step.
