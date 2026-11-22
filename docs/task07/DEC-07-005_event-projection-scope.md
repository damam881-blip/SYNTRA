# Decision Record DEC-07-005 — Event Projection / Pagination Scope in V1

| Field | Value |
|---|---|
| Decision ID | DEC-07-005 |
| Status | **APPROVED** |
| Approval basis | Project owner selected Option A on 2026-11-23 ("أ: تثبيت نطاق V1 صراحةً (موصى به)"). |
| Date | 2026-11-23 |
| Upstream ownership | TASK-05 §6.5 and §12 assign stream/pagination and the subset completeness marker to TASK-07 |
| Scope | TASK-07 draft §8.5 and §13 acceptance matrix |
| Reference artifacts | Unchanged (no file under `contracts/reference/**` is edited) |

## 1. Question

TASK-05 §6.5 requires that any UI/AI subset or paged view of the canonical ordered event stream carry an explicit completeness/selection marker, and §12 assigns pagination/transport ownership to TASK-07. The TASK-07 draft defines only `GET /projects/{project_id}/ping-tests/{test_id}` returning the full immutable `PingTestResult`; its `limit`/`offset` pagination applies only to the project list. No event subset, stream or marker is defined.

## 2. Decision

1. TASK-07 V1 exposes **no** event subset, stream or paged event view. A Ping result read returns the complete immutable `PingTestResult`, including the full ordered `events` array bounded by the TASK-05 40,000-event budget.
2. Because no projection is offered, V1 emits **no** completeness/selection marker. `execution_status: INCOMPLETE`, `observation_status` and diagnostic `evidence_completeness` describe simulation/observation limits only; they never signal HTTP projection truncation.
3. Any future subset or paged event view requires a TASK-07 change request that adds an explicit `selection_complete`/`selection` marker to the **outer envelope** and leaves the stored result bytes and digest untouched.
4. Existing project-list pagination (`limit` default 50, max 100; `offset` default 0) is unrelated to event streams and remains as drafted in §7.1.
5. No new endpoint, Pydantic model, database object or marker field is added in V1.

## 3. Exact insertion text for the TASK-07 draft

### 3.1 §8.5 — append after the second paragraph

After `The API may include command_id and freshness metadata in the outer meta object. The stored result bytes and SHA-256 remain unchanged.`, add:

> V1 exposes no event subset, stream or paged event view. `GET /api/v1/projects/{project_id}/ping-tests/{test_id}` returns the complete immutable `PingTestResult`, including its full ordered `events` array bounded by the TASK-05 40,000-event budget. Consequently no completeness/selection marker is emitted in V1. `execution_status: INCOMPLETE`, `observation_status` and `evidence_completeness` describe simulation and observation limits, never HTTP projection truncation. Any future subset or paged view requires a TASK-07 change request that adds an explicit `selection_complete`/`selection` marker to the outer envelope without modifying the stored result.

### 3.2 §13 acceptance matrix — add one row

In the `Test` column, insert `Event projection scope` immediately after `Ping result`. In the `Expected result` column, insert the matching cell immediately after `Runner output is validated by record_ping_result; result and PingLog are committed once and immutable.`:

> Ping result read returns the full ordered canonical event array; no subset/paged event endpoint exists and no selection marker is emitted.

## 4. Acceptance checks for the later implementation

1. `GET .../ping-tests/{test_id}` returns every persisted event in canonical `(virtual_time_ns, execution_index)` order.
2. No route matching `/events`, `?limit`/`?offset` on a Ping result, or stream/websocket endpoint is registered in V1.
3. An `INCOMPLETE` execution is returned as a valid immutable result, not reinterpreted as a truncated HTTP projection.
4. A future subset proposal is gated on an explicit outer-envelope selection marker; the stored result remains unchanged.

## 5. Files and boundaries

- **New file:** `docs/task07/DEC-07-005_event-projection-scope.md` (this record).
- **Not modified:** the original TASK-07 DOCX, `contracts/reference/task04/**`, `contracts/reference/task05/**`, the continuation package, and any source code.
- **No commit, branch or PR** is created by this decision.
