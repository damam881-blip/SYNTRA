# Transaction Policy — TASK-06

## Concurrency control

- Every aggregate mutation starts with `SELECT ... FROM project WHERE project_id = :id FOR UPDATE`.
- Consistent multi-table reads start with `SELECT ... FOR SHARE` on the project
  row, so a reader can never observe a half-committed mutation.
- Because the project row is the lock root, two mutations on the same project
  serialise; mutations on different projects do not.

## Commit sequence for a mutation

1. Validate input (types, ranges, uniqueness pre-checks).
2. Apply entity changes to the locked aggregate.
3. `project.state_revision += 1`; if the change class is TOPOLOGY,
   CONFIGURATION or MIXED, `project.simulation_revision = state_revision`.
4. `FLUSH` (so the gaplessness trigger sees the bumped counter).
5. Insert the `project_revision` row (gaplessness trigger enforces contiguity).
6. `FLUSH`.
7. Insert the `action_log` row (composite FK to the new revision).
8. Return; the caller's transaction commits once.

`PRESENTATION` and `METADATA` commits bump `state_revision` only.
`save_project` (checkpoint) does not bump any revision.

## Atomicity guarantees

- All work happens in one transaction owned by the caller (`UnitOfWork` or
  `session_scope`).  On any exception the session rolls back and the prior
  committed state is unchanged.
- The database triggers are part of the same transaction, so an invariant
  violation rolls back the whole mutation.
- A persistence failure during step 3–7 leaves no partial row behind.

## Immutability and purge mode

- Historical tables (`project_revision`, `snapshot_ref`, `ping_test_command`,
  `ping_test_result`, `error_envelope`, `action_log`, `ping_log`, `error_log`,
  `checkpoint`, `project_tombstone`) are guarded by
  `syntra_guard_immutable()`.
- Normal writes receive `restrict_violation`.
- Retention and project deletion set `SET LOCAL syntra.purge_mode = 'on'`
  inside their transaction; the flag is transaction-local and resets at commit.

## Consistent retrieval

- `open_project` / `project_document` lock the project row in SHARE mode before
  reading devices, interfaces, connections, routes, revisions and checkpoints.
- Snapshot capture locks the project row in UPDATE mode and records the
  current `state_revision` / `simulation_revision` plus the frozen configuration.
- TASK-05 results reference the snapshot by `(project_id, snapshot_id)`; the
  snapshot's canonical bytes and digest are verified on read.
