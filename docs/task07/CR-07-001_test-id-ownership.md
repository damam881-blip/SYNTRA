# Change Request CR-07-001 — `test_id` Ownership at the Unity ↔ FastAPI Boundary

| Field | Value |
|---|---|
| CR ID | CR-07-001 |
| Status | **APPROVED** |
| Approval basis | Project owner explicitly approved this change on 2026-11-22 ("consider this request approved"). The TASK-05 owner countersignature is to be recorded in the formal handoff register; no upstream artifact is modified byte-for-byte. |
| Date | 2026-11-22 |
| Requester | TASK-07 integration owner |
| Upstream owner | TASK-05 (Ping/evidence/error contracts) |
| Downstream owner | TASK-07 (HTTP/Unity binding) |
| Related decisions | T5-DEC-02, T4-DEC-18, D7-05 |
| Affected requirements | FR-022, FR-023, BR-001, NET-02; no network behaviour change |
| Reference artifacts | Unchanged (SHA-256 verified; no file under `contracts/reference/**` is edited) |

---

## 1. Question

TASK-05 states that `test_id` is backend-created and that the client is not authoritative for test identifier allocation. TASK-07 requires a client-owned correlation key so that a retried Ping submission returns the original result instead of creating a second test. Can Unity propose the UUIDv7 `test_id` while the backend remains authoritative for command acceptance, snapshot capture and all simulation facts?

## 2. Alternatives considered

| Option | Summary | Outcome |
|---|---|---|
| A | Formal CR: allow a client-proposed UUIDv7 `test_id`, backend-validated, as the idempotency/correlation key. | **Chosen** — no database change; existing service already accepts an optional `test_id`. |
| B | Keep backend-only generation; Unity sends a separate `X-Idempotency-Key` and a new mapping table is added in TASK-06. | Rejected — larger scope, new DB object and extra upstream change. |
| C | Defer the decision. | Rejected — blocks TASK-07 approval and the M4 gate. |

## 3. Decision

1. `test_id` remains a **UUIDv7** and remains the canonical identity of one Ping Test in `PingTestCommand` and `PingTestResult`.
2. Unity **proposes** one UUIDv7 per logical Ping action and sends it in the HTTP request. The trusted backend **validates** UUIDv7 format, uniqueness, project/endpoint consistency and contract version, then **accepts** it as the canonical `test_id`.
3. The backend remains the sole authority for command acceptance, immutable snapshot capture, replay input, result validation, persistence and every simulation outcome.
4. `test_id` is the idempotency/correlation key at the HTTP boundary. `X-Request-ID` remains a per-HTTP-request trace identifier and is **not** an idempotency key.
5. Same `test_id` + same `(project_id, source_device_id, destination_device_id, contract_version)` → replay the already stored immutable result; no second command or snapshot is created.
6. Same `test_id` + different request fields → `409 TEST_ID_REUSE_CONFLICT`.
7. The HTTP request keeps `test_id` required, as proposed by TASK-07 §8.1/§11.2. The service-level optional argument remains supported for internal/non-HTTP callers; this CR does not require a service signature change.
8. This CR does **not** change the frozen TASK-05 JSON Schema, the wire vocabulary, the UUIDv7 pattern, any database constraint, or any network/routing/Ping behaviour.

## 4. Rationale

- Removes the contradiction between approved TASK-05 §4/§4.1/T5-DEC-02 and the TASK-07 draft §4.2/§8.4/D7-05 without silently reinterpreting upstream text.
- Satisfies the TASK-07 DoD item “`test_id` is defined for correlation and safe retry; duplicate semantics are tested”.
- Uses existing implementation support: `app/modules/logs/service.py:149-156` accepts an optional `test_id` and generates UUIDv7 only when omitted; `app/db/models/simulation.py:89,105,121` already enforces UUIDv7 shape and uniqueness.
- Keeps the engine as the exclusive authority for network results; the client only supplies a correlation label.

## 5. Exact wording amendments

### 5.1 Upstream TASK-05 document (amendment text for the signoff handoff; original DOCX remains untouched)

- **§4**, replace:
  > The client is not authoritative for snapshot fields or test identifier allocation.

  with:
  > The client is not authoritative for snapshot fields, simulation results or test identity assignment. The client may propose a UUIDv7 `test_id` as an idempotency/correlation key; the trusted backend validates and accepts it as the canonical `test_id` of the command (CR-07-001).

- **§4.1**, `test_id` row, replace:
  > `test_id | UUIDv7 | backend-created identity of this single Ping Test`

  with:
  > `test_id | UUIDv7 | client-proposed, backend-validated canonical identity of this single Ping Test (CR-07-001)`

- **T5-DEC-02**, replace:
  > Backend-internal PingTestCommand includes trusted test_id and immutable snapshot_ref. | Let Unity authorize snapshot fields | Prevents client-generated simulation authority.

  with:
  > Backend-internal PingTestCommand includes a client-proposed but backend-validated trusted test_id and an immutable snapshot_ref. | Let Unity authorize snapshot fields or simulation identity | Prevents client-generated simulation authority while allowing safe HTTP retry correlation (CR-07-001).

- **Master handoff** sentence, replace:
  > Unity does not supply authoritative snapshot fields or allocate test IDs.

  with:
  > Unity does not supply authoritative snapshot fields; it may propose a UUIDv7 `test_id` that the backend validates and accepts (CR-07-001).

### 5.2 TASK-07 draft (amendment text to be applied when the revised draft is issued)

- **§4.2**, `test_id` row: state “Client-proposed UUIDv7 per logical Ping action; backend validates and accepts it as the canonical `test_id` (CR-07-001). Required in the HTTP request and reused for retries.”
- **§8.1**: state that Unity submits `test_id` together with the endpoint IDs and that backend validation/acceptance precedes snapshot capture.
- **§8.4**: replace “Require a client-generated UUIDv7 test_id” with “Require a client-proposed UUIDv7 `test_id`, validated and accepted by the backend (CR-07-001)”.
- **§11.2**: `PingCreateRequest.test_id` stays `UUID`; add the note “UUIDv7 validator required; backend confirms canonical identity (CR-07-001).”
- **D7-05**: evidence becomes “Approved by CR-07-001; upstream TASK-05 §4/§4.1/T5-DEC-02 amended accordingly.”
- **§15.1** blocking list: `test_id` retry behaviour is resolved by CR-07-001, not left open.

## 6. Acceptance criteria for the later TASK-07 implementation

1. `POST /api/v1/projects/{project_id}/ping-tests` with a valid client UUIDv7 `test_id` returns 201; the stored command/result `test_id` equals the submitted value.
2. Replaying the same `test_id` with the same project/source/destination/contract version returns the original immutable result; command/snapshot/result row counts do not increase.
3. Reusing the same `test_id` with any different request field returns `409 TEST_ID_REUSE_CONFLICT` and commits nothing.
4. Malformed, non-v7, or cross-project `test_id` input is rejected by validation with the mapped 422/409 status and leaves committed state unchanged.
5. `X-Request-ID` differs across HTTP retries while `test_id` stays constant; both are echoed/logged correctly.
6. The stored `PingTestCommand` and `PingTestResult` still validate against the unchanged frozen TASK-05 schema; reference artifacts remain byte-identical.

## 7. Files and boundaries

- **New file:** `docs/task07/CR-07-001_test-id-ownership.md` (this document).
- **Not modified:** `contracts/reference/task04/**`, `contracts/reference/task05/**`, the continuation package, and the original TASK-05/TASK-07 DOCX files.
- **No implementation, commit, branch or PR** is created by this CR.
