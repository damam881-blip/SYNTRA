# Decision Record DEC-07-002 — Mutation Response Status Policy

| Field | Value |
|---|---|
| Decision ID | DEC-07-002 |
| Status | **APPROVED** |
| Approval basis | Project owner explicitly approved this resolution on 2026-11-22 ("نعم، تابع" after the project-benefit explanation). |
| Date | 2026-11-22 |
| Scope | TASK-07 draft §7.6 only; §9.2 and §11.3 remain authoritative and unchanged |
| Related tables | §9.2 Proposed HTTP status mapping; §11.3 route/status table; Appendix A.2/A.5 |
| Reference artifacts | Unchanged (no file under `contracts/reference/**` is edited) |

## 1. Question

§7.6 states that successful topology/configuration writes return 200, while §9.2 and §11.3 assign 201 to resource creation (project, device, connection, route, checkpoint, Ping). A single UI action therefore had two documented statuses.

## 2. Decision

1. **201 Created** for resource-creating writes: project, device, connection, static route, checkpoint and Ping test.
2. **200 OK** for updates and deletions of existing resources (rename/move/rotate/admin-state/IPv4/gateway/remove/delete project), with the refreshed canonical `ProjectStateDocument` or a dedicated receipt in `data`.
3. §9.2 and §11.3 are **not** changed. §7.6 is corrected to match them; this is the smallest change and preserves the already-drafted OpenAPI examples.
4. No implementation, database constraint or upstream contract is affected by this documentation correction.

## 3. Exact replacement text for TASK-07 draft §7.6

Replace the first sentence of §7.6 (starting `PROPOSAL: successful topology/configuration writes return 200 ...` and ending `... returns 200 with a deletion receipt.`) with:

> PROPOSAL: resource-creating writes return 201 Created with the created resource or receipt in `data`, a `Location` header where applicable, and the new ETag. This applies to project, device, connection, static-route, checkpoint and Ping-test creation. Updates and deletions of existing resources return 200 OK with the refreshed canonical ProjectStateDocument in `data` (project deletion returns a deletion receipt instead), plus the new ETag. This keeps Unity's local scene model synchronized with the committed backend state and returns all newly allocated IDs.

The second paragraph of §7.6 (rejected writes, rollback, retained last known committed state, error response with request ID) remains unchanged.

## 4. Acceptance checks for the later implementation

1. Every creation endpoint in §11.3 returns 201 and the OpenAPI response declaration matches §9.2.
2. Every update/delete endpoint in §11.3 returns 200 with the refreshed state document or receipt.
3. Appendix A examples show 201 for Ping submission/network-failure-as-valid-result and 200 for mutation receipts, consistent with §9.2.
4. A rejected write still returns no partial `ProjectStateDocument`; the transaction rolls back and the new ETag is not emitted.

## 5. Files and boundaries

- **New file:** `docs/task07/DEC-07-002_mutation-status-policy.md` (this record).
- **Not modified:** the original TASK-07 DOCX, `contracts/reference/task04/**`, `contracts/reference/task05/**`, the continuation package, and any source code.
- **No commit, branch or PR** is created by this decision.
