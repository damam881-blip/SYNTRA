# TASK-07 Contract Sign-off v1.1

| Field | Value |
|---|---|
| Artifact | `docs/task07/SIGNOFF_v1.1.md` |
| Signed bundle | `TASK07_AMENDMENT_BUNDLE_v1.1.md` |
| Bundle SHA-256 | `F4E4B0FC329C8F2B45CF71C209B421CCEE7500611F4D42E36899AA4A78F17580` |
| Date | 2026-11-23 |
| Status | **APPROVED — CONTRACT DECISIONS ONLY** |
| Approver | Project owner (explicit instruction: “وقّع الحزمة فقط” / “sign the bundle only”) |
| Scope | §14.2 step 1 — approval of the TASK-07 contract decisions |
| Not included | §14.2 steps 2–10 (API implementation, routers, guard, Ping adapter, OpenAPI, API tests) — these remain gated by a separate owner instruction |

## 1. Approved artifacts

| Decision | Subject | Status |
|---|---|---|
| CR-07-001 | Client-proposed UUIDv7 `test_id`, backend-validated and accepted as canonical idempotency key | APPROVED |
| DEC-07-002 | 201 Created for resource creation, 200 OK for updates/deletions; correct §7.6 only | APPROVED |
| DEC-07-003 | `is_current: bool \| None = None` in `ApiMeta`, derived from `evidence_freshness` | APPROVED |
| DEC-07-004 | `If-Match` required on `DELETE /projects/{project_id}` with 428/412 and `confirm_name` | APPROVED |
| DEC-07-005 | V1 returns the full immutable event array; no event subset/stream/paged view and no selection marker | APPROVED |
| IMP-07-001 | TASK-02 MDI/cable matrix and IPv4 exclusions enforced in the TASK-06 service | IMPLEMENTED AND VERIFIED |

## 2. Approval statement

The project owner approves the consolidated TASK-07 amendment bundle v1.1 and the decisions recorded above. The TASK-07 contract draft, as amended by that bundle, is accepted for formal sign-off. This approval resolves the five blocking findings from the audit and the separate non-blocking TASK-02/TASK-06 structural-validation gap.

## 3. Evidence recorded at sign-off

- Verification: `405 passed in ~59s` (previous baseline 316 plus 89 new tests from IMP-07-001).
- `ruff check` and `ruff format --check`: clean for all changed Python files.
- Frozen artifacts (`contracts/reference/task04/**`, `contracts/reference/task05/**`, continuation package, original DOCX files): unchanged.
- Repository: one modified TASK-06 service file plus new untracked validation module, tests and `docs/task07/` records. No Task 7 API code, commit, branch or PR.

## 4. Boundaries

1. No original DOCX or frozen contract is edited; amendments remain in the new `docs/task07/` artifacts.
2. This signature does **not** authorize implementation work. Each §14.2 step from 2 onward requires its own explicit owner go-ahead.
3. `app/main.py` still exposes only `/health`; no `/api/v1` router, envelope, ETag guard, Ping adapter or OpenAPI snapshot exists yet.
