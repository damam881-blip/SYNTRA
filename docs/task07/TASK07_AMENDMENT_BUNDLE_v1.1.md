# TASK-07 Amendment Bundle v1.1 — Consolidated Resolution of Blocking Points 1–5

| Field | Value |
|---|---|
| Bundle | TASK07_AMENDMENT_BUNDLE_v1.1 |
| Date | 2026-11-23 |
| Status | **SIGNED — CONTRACT APPROVED** on 2026-11-23 (`SIGNOFF_v1.1.md`, §14.2 step 1); Task 7 API implementation not started |
| Base document | `TASK-07_Unity_FastAPI_API_State_Revision_Specification_v1.0_DRAFT conv.docx` (unchanged; amendments are applied by the spec owner to a revised copy) |
| Decision records | `CR-07-001_test-id-ownership.md`, `DEC-07-002_mutation-status-policy.md`, `DEC-07-003_api-meta-is-current.md`, `DEC-07-004_delete-if-match.md`, `DEC-07-005_event-projection-scope.md` |
| Separate non-blocking fix | `IMP-07-001_structural-validation-fix.md` — TASK-02 MDI/cable matrix and IPv4 exclusions wired into the TASK-06 service, verified by 405 passing tests |
| Frozen artifacts | `contracts/reference/task04/**`, `contracts/reference/task05/**`, continuation package and original DOCX files are **not modified** |
| Repository state | New untracked docs/tests plus one modified TASK-06 service file; no Task 7 API code, commit, branch or PR |

## 1. Resolution register

| # | Blocking point | Decision | Scope |
|---|---|---|---|
| 1 | `test_id` ownership conflict with approved TASK-05 §4/§4.1/T5-DEC-02 | CR-07-001 APPROVED — client-proposed UUIDv7, backend-validated and accepted as canonical idempotency key; no DB change | §4.2, §8.1, §8.4, §11.2, D7-05, §15.1 + upstream amendment text |
| 2 | 200 vs 201 contradiction | DEC-07-002 APPROVED — 201 for creations, 200 for updates/deletions; correct §7.6 only | §7.6 |
| 3 | `is_current` missing from `ApiMeta` under `extra="forbid"` | DEC-07-003 APPROVED — add optional `is_current: bool \| None = None`, invariant `is_current == (evidence_freshness == "CURRENT")` | §8.6, §11.2, Appendix A.3 (A.4 already correct) |
| 4 | `If-Match` omitted from DELETE project description | DEC-07-004 APPROVED — require `If-Match`, 428/412, keep `confirm_name`, add 428 to OpenAPI | §7.1, §11.3 |
| 5 | TASK-05 §6.5/§12 stream/pagination + completeness marker unaddressed | DEC-07-005 APPROVED — V1 returns full immutable result, no event subset/stream/paged view and no selection marker; future subset requires a CR | §8.5, §13 |

## 2. Consolidated exact amendments (in document order)

### 2.1 §4.2 `test_id` row (CR-07-001)

State: “Client-proposed UUIDv7 per logical Ping action; backend validates and accepts it as the canonical `test_id` (CR-07-001). Required in the HTTP request and reused for retries.”

### 2.2 §7.1 DELETE line (DEC-07-004)

Replace the DELETE line with:

> DELETE /api/v1/projects/{project_id} — requires `If-Match: <ETag from the last project read>`; a missing header returns 428 Precondition Required, and a stale ETag returns 412 Precondition Failed with no deletion committed. The request body contains `confirm_name` matching the exact stored project name. Response: 200 deletion receipt from the tombstone, not the deleted project document. This preserves the confirmation behavior of the existing service.

### 2.3 §7.6 first paragraph (DEC-07-002)

Replace the first paragraph with:

> PROPOSAL: resource-creating writes return 201 Created with the created resource or receipt in `data`, a `Location` header where applicable, and the new ETag. This applies to project, device, connection, static-route, checkpoint and Ping-test creation. Updates and deletions of existing resources return 200 OK with the refreshed canonical ProjectStateDocument in `data` (project deletion returns a deletion receipt instead), plus the new ETag. This keeps Unity's local scene model synchronized with the committed backend state and returns all newly allocated IDs.

The second paragraph of §7.6 is unchanged.

### 2.4 §8.1 Ping request (CR-07-001)

State that Unity submits `test_id` together with the endpoint IDs and that backend validation/acceptance precedes snapshot capture; the client never supplies snapshot or revision fields.

### 2.5 §8.4 retry handling (CR-07-001)

Replace “Require a client-generated UUIDv7 test_id” with “Require a client-proposed UUIDv7 `test_id`, validated and accepted by the backend (CR-07-001)”. Same ID + same payload replays; same ID + different payload → `409 TEST_ID_REUSE_CONFLICT`.

### 2.6 §8.5 final paragraph (DEC-07-005)

Append:

> V1 exposes no event subset, stream or paged event view. `GET /api/v1/projects/{project_id}/ping-tests/{test_id}` returns the complete immutable `PingTestResult`, including its full ordered `events` array bounded by the TASK-05 40,000-event budget. Consequently no completeness/selection marker is emitted in V1. `execution_status: INCOMPLETE`, `observation_status` and `evidence_completeness` describe simulation and observation limits, never HTTP projection truncation. Any future subset or paged view requires a TASK-07 change request that adds an explicit `selection_complete`/`selection` marker to the outer envelope without modifying the stored result.

### 2.7 §8.6 final sentence (DEC-07-003)

Append:

> `is_current` is derived as `is_current == (evidence_freshness == "CURRENT")`. It must never contradict `evidence_freshness`; for non-Ping responses it is omitted (`None`). It is computed at read time and is never persisted inside `PingTestResult`.

### 2.8 §11.2 `ApiMeta` (DEC-07-003)

```python
class ApiMeta(StrictModel):
    api_version: Literal["v1"] = "v1"
    request_id: str | None = None
    command_id: UUID | None = None
    evidence_freshness: Literal["CURRENT", "STALE"] | None = None
    result_base_simulation_revision: int | None = None
    current_simulation_revision: int | None = None
    is_current: bool | None = None
```

`PingCreateRequest.test_id` stays `UUID` with the note “UUIDv7 validator required; backend confirms canonical identity (CR-07-001).”

### 2.9 §11.3 `deleteProject` responses (DEC-07-004)

```yaml
"200": { description: Deletion receipt } "412": { description: Stale project state } "428": { description: Missing If-Match }
```

The `If-Match required: true` parameter is unchanged.

### 2.10 §13 acceptance matrix (DEC-07-005)

Add test `Event projection scope` after `Ping result` and the matching expected result after `Runner output is validated by record_ping_result; result and PingLog are committed once and immutable.`:

> Ping result read returns the full ordered canonical event array; no subset/paged event endpoint exists and no selection marker is emitted.

### 2.11 §15.1 blocking list and D7-05 (CR-07-001)

- `test_id` retry behaviour: resolved by CR-07-001, not left open.
- D7-05 evidence: “Approved by CR-07-001; upstream TASK-05 §4/§4.1/T5-DEC-02 amended accordingly.”

### 2.12 Appendix A.3 and A.4 (DEC-07-003)

- A.3 `meta`: add `, "is_current": true` after `current_simulation_revision: 10`.
- A.4: unchanged (`STALE` + `is_current: false` already satisfies the invariant).

### 2.13 Upstream TASK-05 amendment text (CR-07-001 §5.1 — for signoff handoff only)

Not applied to any frozen file or original DOCX. The approved replacement text for TASK-05 §4, §4.1 `test_id` row, T5-DEC-02 and the master handoff sentence is recorded verbatim in `CR-07-001_test-id-ownership.md` §5.1.

## 3. Sections deliberately unchanged

- §5.2, §9.2 and D7-02: already require `If-Match`/428/412 correctly.
- §11.1 `StrictModel(extra="forbid")`: remains; the new `is_current` field is now declared.
- §8.5 immutable `PingTestResult` and §8.7 network-vs-HTTP failure policy.
- §11.3 all response codes except the added `428` on `deleteProject`.
- All frozen TASK-04/TASK-05 schemas, wire vocabulary, UUIDv7 pattern, DB constraints and engine behavior.

## 4. Gate status and next sequence

1. Points 1–5 are resolved; **§14.2 step 1 “Approve the contract decisions” is complete** — see `SIGNOFF_v1.1.md`.
2. §14.2 steps 2–10 (strict schemas → DB lifecycle → routers → revision guard → query projections → Ping adapter → error mapping → OpenAPI → tests) require a separate explicit owner go-ahead; the signature covers step 1 only.
3. No Task 7 API implementation exists in the repository at this point; `app/main.py` exposes only `/health`. The separate TASK-06 structural-validation fix (IMP-07-001) does not add any Task 7 route or contract.
4. Verification baseline is now `405 passed in 55.59s` (previous 316 plus 89 new tests from IMP-07-001); see `docs/task07/IMP-07-001_structural-validation-fix.md`.
5. No commit, push or PR is created by this bundle.
