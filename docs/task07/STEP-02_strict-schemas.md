# TASK-07 §14.2 Step 2 — Strict Pydantic Schemas

| Field | Value |
|---|---|
| Step | §14.2 step 2 (strict schemas) |
| Status | **IMPLEMENTED AND VERIFIED** |
| Date | 2026-11-23 |
| Authorization | Owner instruction “ممكن نبدأ” after the v1.1 contract sign-off; step 2 only |
| Verification | `466 passed` (405 prior + 60 new schema tests + 1 route-edit regression test added under owner approval during step 2); `ruff check` and `ruff format --check` clean across `app` and `tests` |
| Not included | Routers, `/api/v1` mounting, DB session wiring, revision guard, Ping adapter, error-handler mapping, OpenAPI snapshot |

## 1. Files added

| File | Purpose |
|---|---|
| `app/api/__init__.py`, `app/api/v1/__init__.py` | New API package skeleton |
| `app/api/v1/schemas.py` | All step-2 data shapes |
| `tests/unit/test_api_schemas.py` | 60 strictness/validator/envelope tests |
| `docs/task07/STEP-02_strict-schemas.md` | This record |

`app/main.py` is unchanged and still exposes only `/health`.

## 2. Schema inventory

- **Base/envelope**: `StrictModel` (`extra="forbid"`), `ApiMeta`, `ApiEnvelope[T]`, `ProjectEnvelope`, `PingEnvelope`.
- **Validators**: `UUIDv7` (`Annotated[UUID, AfterValidator(...)]`) and `IPv4Text` (delegates to the engine's strict `parse_ipv4`).
- **Requests**: `ProjectCreateRequest`, `DeleteProjectRequest`, `CheckpointCreateRequest`, `PositionIn`, `DeviceCreateRequest`, `DeviceRenameRequest`, `RotationRequest`, `AdminStateRequest`, `InterfaceIPv4Request`, `GatewayRequest`, `ConnectionCreateRequest`, `StaticRouteCreateRequest`, `StaticRoutePatchRequest`, `PingCreateRequest`.
- **Errors**: `ValidationIssue`, `StaleStateDetails`, `ErrorDetail`, `ErrorEnvelope` — exactly the existing `{"error":{"code","message","details","request_id"}}` shape.

## 3. Contract decisions applied

1. `is_current: bool | None = None` is declared in `ApiMeta` and enforced by an after-validator: `CURRENT → True`, `STALE → False`, absent freshness → `None`. `ApiMeta.for_ping(...)` derives both values from the two simulation revisions (DEC-07-003).
2. Every ID field, including `ApiMeta.command_id`, is UUIDv7-validated; Pydantic's generic UUID parsing alone is not trusted.
3. IPv4 fields reject non-ASCII digits, leading zeros, wrong octet counts and out-of-range octets by reusing the engine parser (T2-01/T2-02).
4. `test_id` is client-supplied in `PingCreateRequest` and validated as UUIDv7 (CR-07-001).
5. Prefix bounds: interface `/1…/30`, static route `/0…/32`; rotation is `[-180, 180)`.
6. `StaticRoutePatchRequest` requires at least one editable field and forbids backend-owned fields (`route_id`, `route_sequence`).
7. Extra fields are rejected at every level, including nested `PositionIn` and the response envelope.

## 4. Deliberate implementation choices

- `ApiEnvelope` derives from `StrictModel` (the §11.2 draft used plain `BaseModel`); forbidding unknown envelope fields is stricter and does not change the documented `data`/`meta` shape.
- PEP 695 syntax `class ApiEnvelope[T](StrictModel)` is used instead of `Generic[T]`; it is equivalent under Python 3.12 and required by the repository's `UP046` lint rule.
- `ProjectStateDocument` and `PingTestResult` are **not** re-declared as Pydantic models. §11.4 requires contract tests to validate those nested documents against the frozen JSON Schemas; response envelopes use `CanonicalDocument = dict[str, Any]` for `data` and remain generic.
- No distinct-endpoint or route-alignment check was added to the request layer: §7.4/§9.4 assign those to the service, and moving them would change the HTTP status from 409 to 422.

## 5. Verification detail

- New tests: 60 (extra fields, UUIDv7 on every ID field, strict IPv4 across three DTOs, prefix/rotation bounds, freshness invariant in both directions, envelope round-trip, error-envelope shape, route-patch rules).
- Full suite: **466 passed**; no pre-existing test regressed.
- During step 2, the owner also approved closing a discovered gap in `edit_static_route` (IMP-07-001 follow-up): editing a static route now applies the same special-use next-hop guard as creation. One PostgreSQL regression test was added.
- Frozen artifacts and original DOCX files untouched; no commit, push or PR action in this step.
