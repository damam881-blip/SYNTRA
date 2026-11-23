# TASK-07 §14.2 Step 5 — If-Match Revision Guard

| Field | Value |
|---|---|
| Step | §14.2 step 5 (implement revision guard) |
| Status | **IMPLEMENTED AND VERIFIED** |
| Date | 2026-11-23 |
| Authorization | Owner instruction “انتقل للخطوة 5: revision guard (موصى به)” |
| Contract basis | §5.2, §9.2, Appendix A.2, decision D7-02 (signed v1.1 bundle) |
| Verification | `510 passed in 79.39s` (492 prior + 10 unit + 8 PostgreSQL integration tests); `ruff check` and `ruff format --check` clean across `app` and `tests` |
| Not included | Query projections (step 6), Ping adapter (step 7), persistence-error mapping (step 8), OpenAPI snapshot artifact (step 9) |

## 1. Files added/changed

| File | Change |
|---|---|
| `app/api/v1/revision.py` | New: `PreconditionRequiredError` (428), `StaleProjectStateError` (412), `require_if_match` dependency |
| `app/api/v1/projects.py` | Guard on `DELETE /projects/{id}` and `POST …/checkpoints` |
| `app/api/v1/devices.py` | Guard on all 7 device/gateway operations |
| `app/api/v1/interfaces.py` | Guard on all 3 interface operations |
| `app/api/v1/connections.py` | Guard on both connection operations |
| `app/api/v1/static_routes.py` | Guard on all 3 route operations |
| `tests/unit/test_revision_guard.py` | 10 tests: revision-suffix parsing, error status/code, OpenAPI header declaration |
| `tests/integration/db/test_api_revision_guard.py` | 8 PostgreSQL tests incl. a true concurrent-write lock test |
| `tests/integration/db/test_api_v1_routers.py` | Step-4 tests updated to thread the current ETag through every protected write |
| `docs/task07/STEP-05_revision-guard.md` | This record |

## 2. Guard behavior

1. **Coverage (D7-02):** all 17 project-scoped writes require `If-Match` — project delete, checkpoint save, and every device/interface/connection/static-route mutation. Project creation and all reads are unprotected.
2. **Same-transaction check:** `require_if_match` is a FastAPI dependency sharing the request-scoped session (dependency caching), so it locks the project row `FOR UPDATE` via the existing `lock_project` and compares the header inside the very transaction that will run the service. The service's own `_lock` re-enters the already-held lock; no second transaction is opened.
3. **Missing header → 428** `PRECONDITION_REQUIRED`; nothing is locked or mutated.
4. **Mismatch → 412** `STALE_PROJECT_STATE` with details `{expected_state_revision, current_state_revision, current_simulation_revision}` exactly as Appendix A.2; the transaction rolls back through the step-3 dependency, so no partial state is committed.
5. **Exact comparison:** the header must equal `"p-{project_id}-s{state_revision}"` byte-for-byte. Weak validators (`W/…`), `*`, lists and malformed tokens all fail the comparison (412).
6. Both errors are `AppError` subclasses, so they flow through the existing handler and preserve the outer `{"error":{"code","message","details","request_id"}}` envelope with the echoed request ID.

## 3. Deliberate implementation choices

- The `If-Match` header is declared **optional in OpenAPI** (`str | None`, default `None`) while enforcement is runtime 428. Declaring it `required=True` would make FastAPI answer 422 for a missing header, contradicting §5.2/§9.2. The header still appears as a parameter on every protected operation (asserted by unit tests).
- `expected_state_revision` is parsed best-effort from the `-s{revision}"` suffix. An unparseable token still yields 412; the sentinel `0` is reported because persisted revisions are positive integers. This edge is not specified by the draft and is recorded here as the chosen behavior.
- A protected write against a non-existent project with a well-formed header currently surfaces `ProjectNotFoundError` as 500; the 404 translation belongs to step 8 and was not pre-empted here.

## 4. Verification detail

- Unit (10): suffix parsing incl. weak/malformed/`*` tokens; 428/412 status+code pairs; all 17 protected operations declare `If-Match` in OpenAPI; create/open do not.
- Integration (8, PostgreSQL): 428 with no revision advance or device row; 412 with exact A.2 details and unchanged stored state; sequential same-ETag double write (one 201, one 412, one device); **concurrent** same-ETag writes via two threads (exactly one 201 and one 412, revision 2, one device) proving the row lock serializes the check-and-mutate; checkpoint and delete require the header; malformed token → 412 with sentinel; reads/creation stay unprotected.
- Step-4 integration tests now thread the ETag through every mutation and still assert per-step revision/ETag progression.
- Full suite: **510 passed in 79.39s**; no pre-existing test regressed.
- Frozen artifacts and original DOCX files untouched; no commit, push or PR action in this step.
