# TASK-07 §14.2 Step 4 — Mount `/api/v1` Routers

| Field | Value |
|---|---|
| Step | §14.2 step 4 (mount `/api/v1` routers) |
| Status | **IMPLEMENTED AND VERIFIED** |
| Date | 2026-11-23 |
| Authorization | Owner instruction “انتقل للخطوة 4: mount routers” |
| Verification | `492 passed in 80.70s` (472 prior + 6 unit route/DTO tests + 14 PostgreSQL API integration tests); `ruff check` and `ruff format --check` clean across `app` and `tests` |
| Not included | `If-Match` enforcement (step 5), collection/query projections (step 6), Ping endpoints (step 7), persistence-error mapping (step 8), OpenAPI snapshot artifact (step 9) |

## 1. Files added/changed

| File | Purpose |
|---|---|
| `app/api/v1/common.py` | `project_etag`, `meta_for`, `canonical_response`, receipt serializers |
| `app/api/v1/projects.py` | create / open / delete project, save checkpoint |
| `app/api/v1/devices.py` | add / rename / move / rotate / remove device, set / clear host gateway |
| `app/api/v1/interfaces.py` | admin-state PATCH, ipv4 PUT / DELETE |
| `app/api/v1/connections.py` | add / remove connection |
| `app/api/v1/static_routes.py` | add / edit / delete static route |
| `app/api/v1/router.py` | Aggregate `api_v1_router` |
| `app/api/v1/schemas.py` | Added `DevicePositionRequest` (step-2 follow-up) and the dedicated `CheckpointReceipt` / `DeletionReceipt` DTOs + envelopes required by §11.4 |
| `app/main.py` | `app.include_router(api_v1_router, prefix="/api/v1")`; `/health` preserved |
| `tests/unit/test_api_routes.py` | 6 tests: mounted surface via OpenAPI, deferred endpoints absent, unique operation IDs, position DTO strictness |
| `tests/integration/db/test_api_v1_routers.py` | 14 PostgreSQL-backed API tests |
| `docs/task07/STEP-04_routers-mounted.md` | This record |

## 2. Mounted surface (19 operations)

- Projects: `POST /projects` (201), `GET /projects/{project_id}` (200), `DELETE /projects/{project_id}` (200 tombstone receipt), `POST /projects/{project_id}/checkpoints` (201 receipt).
- Devices: `POST …/devices` (201); `PATCH …/{device_id}/name|position|rotation` (200); `DELETE …/{device_id}` (200); `PUT|DELETE …/{device_id}/default-gateway` (200).
- Interfaces: `PATCH …/{interface_id}/admin-state`, `PUT|DELETE …/{interface_id}/ipv4` (200).
- Connections: `POST …/connections` (201), `DELETE …/connections/{connection_id}` (200).
- Static routes: `POST …/static-routes` (201), `PATCH|DELETE …/static-routes/{route_id}` (200).

All paths match the §6 catalogue exactly; `operation_id` values follow the §11.3 camelCase naming (`createProject`, `openProject`, `deleteProject`, `addDevice`, …).

## 3. Contract behavior implemented

1. **Mutation responses** (§7.6): every topology/configuration write returns the refreshed canonical `ProjectStateDocument` in `data`, rendered by `open_project` **inside the same request transaction** as the mutation, plus the new `ETag: "p-{project_id}-s{state_revision}"` (§5.2 format).
2. **Status codes**: 201 for project/device/connection/route/checkpoint creation; 200 for updates and deletions. No 204 is used, because deletions return the refreshed document (or a receipt) per §7.
3. **Receipts** (§11.4): checkpoint save returns a dedicated `CheckpointReceipt` (revision unchanged, ETag unchanged); project delete returns a `DeletionReceipt` built from the surviving tombstone, with no ETag.
4. **Envelope/meta**: every success carries `ApiMeta` with `api_version="v1"` and the middleware `request_id`; `X-Request-ID` is echoed.
5. **Validation**: all path IDs are UUIDv7-validated; request bodies use the step-2 strict DTOs; failures surface through the existing handler as 422 with the preserved outer `{"error":{…}}` envelope.
6. **Thin layer**: handlers only translate DTOs and call the existing services; no persistence rule was moved into the API, and services still never commit (the step-3 dependency owns the transaction).

## 4. Deliberate implementation choices

- Session injection uses `Annotated[Session, Depends(get_db_session)]` (no default-argument call) to satisfy the repository's `B008` lint rule; behavior is identical.
- Route-mounting unit tests introspect `app.openapi()` rather than `app.routes`: FastAPI 0.158 keeps included routers lazy (`_IncludedRouter`), so the flat route list is not the authoritative surface. The OpenAPI document is also the step-9 artifact source.
- `If-Match` is intentionally **not declared or enforced yet**: declaring a required header without enforcement would misrepresent the contract. Step 5 adds the lock-and-compare guard and the header declaration together.
- Persistence exceptions (`ProjectNotFoundError`, `IntegrityConflictError`, `PreconditionConflictError`, `DeletionConfirmationError`, `ContractValidationError`) still surface as 500 through the generic handler; their HTTP mapping is step 8, and no test asserts the interim behavior.
- Collection reads (`GET /projects`, device/interface/connection/route lists, revisions, checkpoint list) are deferred to step 6 per the approved step-4 scope.

## 5. Verification detail

- Unit (6): all 19 expected `(method, path)` pairs present under `/api/v1`; `/health` preserved; step-6/7 endpoints absent; operation IDs unique and named; `DevicePositionRequest` requires the `{position:{x,y,z}}` wrapper and forbids extras at both levels.
- Integration (14, PostgreSQL): create/open with ETag and canonical document equality; request-ID echo; tombstone receipt; checkpoint receipt with unchanged revision/ETag; full device lifecycle advancing `state_revision` exactly once per mutation (2→8) with per-step ETag checks; position-wrapper 422; interface admin-state/ipv4 lifecycle; connection lifecycle; static-route lifecycle; 422 error-envelope shape for extra fields, non-UUIDv7 path IDs and empty route PATCH.
- Full suite: **492 passed in 80.70s**; no pre-existing test regressed.
- Frozen artifacts and original DOCX files untouched; no commit, push or PR action in this step.
