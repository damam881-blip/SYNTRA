# Decision Record DEC-07-004 — `If-Match` on Project Deletion

| Field | Value |
|---|---|
| Decision ID | DEC-07-004 |
| Status | **APPROVED** |
| Approval basis | Project owner selected Option A on 2026-11-23 ("أ: أضف If-Match إلى §7.1 وأكمل §11.3 (موصى به)"), including recording the decision and advancing to point 5. |
| Date | 2026-11-23 |
| Scope | TASK-07 draft §7.1 and §11.3 |
| Related sections | §5.2 (ETag/If-Match policy), §9.2 (428/412), §15 D7-02 (approved recommendation) |
| Reference artifacts | Unchanged (no file under `contracts/reference/**` is edited) |

## 1. Question

§5.2, §9.2, §11.3 and D7-02 require `If-Match` for every project-scoped write, but the §7.1 description of `DELETE /projects/{project_id}` mentions only the `confirm_name` body and the 200 receipt. Deletion is the highest-risk write and must not proceed against a project whose state changed after the client read it.

## 2. Decision

1. `DELETE /api/v1/projects/{project_id}` requires `If-Match` carrying the ETag from the last project read.
2. Missing header → 428 Precondition Required. Stale ETag → 412 Precondition Failed, with no deletion committed. `confirm_name` remains an additional, independent confirmation guard.
3. Successful deletion still returns 200 with the tombstone deletion receipt, not the deleted project document.
4. §11.3 gains an explicit `428` response for `deleteProject` so the generated OpenAPI matches §9.2 and §5.2.
5. §5.2, §9.2 and D7-02 remain unchanged; they were already correct. No service signature or database change is required: `app/modules/projects/service.py:371-402` already locks the project row inside the caller's transaction.

## 3. Exact replacement / insertion text for the TASK-07 draft

### 3.1 §7.1 — replace the DELETE line

Replace:

> DELETE /api/v1/projects/{project_id} — request body contains confirm_name matching the exact stored project name. Response: 200 deletion receipt from the tombstone, not the deleted project document. This preserves the confirmation behavior of the existing service.

with:

> DELETE /api/v1/projects/{project_id} — requires `If-Match: <ETag from the last project read>`; a missing header returns 428 Precondition Required, and a stale ETag returns 412 Precondition Failed with no deletion committed. The request body contains `confirm_name` matching the exact stored project name. Response: 200 deletion receipt from the tombstone, not the deleted project document. This preserves the confirmation behavior of the existing service.

### 3.2 §11.3 — extend the `deleteProject` responses

Replace:

```yaml
"200": { description: Deletion receipt } "412": { description: Stale project state }
```

with:

```yaml
"200": { description: Deletion receipt } "412": { description: Stale project state } "428": { description: Missing If-Match }
```

The existing `If-Match required: true` parameter declaration remains unchanged.

## 4. Acceptance checks for the later implementation

1. DELETE without `If-Match` returns 428 and writes no tombstone.
2. DELETE with an ETag that does not match the current `state_revision` returns 412 and writes no tombstone.
3. DELETE with the current ETag and a matching `confirm_name` returns 200 and a tombstone receipt; the old project document is not returned.
4. DELETE with the current ETag but a wrong `confirm_name` still returns the mapped confirmation error and commits nothing.
5. The ETag comparison and the service deletion occur in the same locked transaction.

## 5. Files and boundaries

- **New file:** `docs/task07/DEC-07-004_delete-if-match.md` (this record).
- **Not modified:** the original TASK-07 DOCX, `contracts/reference/task04/**`, `contracts/reference/task05/**`, the continuation package, and any source code.
- **No commit, branch or PR** is created by this decision.
