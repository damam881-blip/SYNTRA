# Decision Record DEC-07-003 — `is_current` in `ApiMeta`

| Field | Value |
|---|---|
| Decision ID | DEC-07-003 |
| Status | **APPROVED** |
| Approval basis | Project owner selected Option A on 2026-11-23 ("أ: أضف is_current إلى ApiMeta (موصى به)"), including recording the decision and advancing to point 4. |
| Date | 2026-11-23 |
| Scope | TASK-07 draft §8.6, §11.2 and Appendix A.3; Appendix A.4 already conforms |
| Related sections | §11.1 (`StrictModel`, `extra="forbid"`), §11.3 (Ping freshness fields in `ApiMeta`), §8.5 (immutable result) |
| Reference artifacts | Unchanged (no file under `contracts/reference/**` is edited) |

## 1. Question

§8.6 and Appendix A.4 use `is_current` as a Ping read-time freshness projection, but `ApiMeta` in §11.2 does not declare it. Because `ApiMeta` inherits `StrictModel` with `extra="forbid"`, a compliant response containing `is_current` would fail Pydantic validation.

## 2. Decision

1. Add `is_current: bool | None = None` to `ApiMeta` in §11.2.
2. Define it in §8.6 as a read-time projection with the invariant `is_current == (evidence_freshness == "CURRENT")`. It must never contradict `evidence_freshness` and must never be written into the immutable `PingTestResult`.
3. For non-Ping responses the field is omitted (serialized as `null`/absent through the `None` default); no other endpoint changes.
4. Keep Appendix A.4 unchanged (`STALE` + `is_current: false` is already correct), and add `is_current: true` to Appendix A.3 to demonstrate the invariant.
5. No separate `PingApiMeta` model is introduced; §11.3 already places Ping-specific freshness fields in `ApiMeta`.

## 3. Exact replacement / insertion text for the TASK-07 draft

### 3.1 §11.2 — replace the `ApiMeta` class block

Replace:

```python
class ApiMeta(StrictModel):
    api_version: Literal["v1"] = "v1"
    request_id: str | None = None
    command_id: UUID | None = None
    evidence_freshness: Literal["CURRENT", "STALE"] | None = None
    result_base_simulation_revision: int | None = None
    current_simulation_revision: int | None = None
```

with:

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

### 3.2 §8.6 — append to the final sentence of the section

After `Suggested Ping read metadata: evidence_freshness, result_base_simulation_revision, current_simulation_revision, and is_current. These are read-time projections and must not be written into the immutable PingTestResult.`, add:

> `is_current` is derived as `is_current == (evidence_freshness == "CURRENT")`. It must never contradict `evidence_freshness`; for non-Ping responses it is omitted (`None`). It is computed at read time and is never persisted inside `PingTestResult`.

### 3.3 Appendix A.3 — update the `meta` object

Replace:

```json
"command_id": "019a5000-0000-7000-8000-000000000015", "evidence_freshness": "CURRENT", "result_base_simulation_revision": 10, "current_simulation_revision": 10
```

with:

```json
"command_id": "019a5000-0000-7000-8000-000000000015", "evidence_freshness": "CURRENT", "result_base_simulation_revision": 10, "current_simulation_revision": 10, "is_current": true
```

### 3.4 Appendix A.4

No change: `"evidence_freshness": "STALE"` with `"is_current": false` already satisfies the invariant.

## 4. Acceptance checks for the later implementation

1. A Ping read with matching revisions yields `evidence_freshness: "CURRENT"` and `is_current: true`.
2. A Ping read with advanced `simulation_revision` yields `"STALE"` and `is_current: false`.
3. No state-revision-only change flips `is_current`; freshness semantics remain governed by `simulation_revision` as in §8.6.
4. `ApiMeta` accepts `is_current` under `extra="forbid"`; non-Ping envelopes omit it without validation errors.
5. The stored `PingTestResult` bytes and digest remain unchanged; freshness fields exist only in the outer envelope.

## 5. Files and boundaries

- **New file:** `docs/task07/DEC-07-003_api-meta-is-current.md` (this record).
- **Not modified:** the original TASK-07 DOCX, `contracts/reference/task04/**`, `contracts/reference/task05/**`, the continuation package, and any source code.
- **No commit, branch or PR** is created by this decision.
