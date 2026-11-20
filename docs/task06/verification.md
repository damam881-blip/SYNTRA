# Verification Report — TASK-06

## Automated checks

| Check | Result |
|---|---|
| `ruff check app migrations` | 0 errors |
| `pytest -q` (unit + contract + integration) | 316 passed, 0 failed |
| PostgreSQL integration suite (`tests/integration/db`) | 33 passed |
| Alembic `upgrade head` / `downgrade base` / `upgrade head` | success; covered by PostgreSQL integration test |
| `pglast` parse of `app/db/sql/constraints.sql` | 0 syntax errors |

## Contract verification

- All 5 approved TASK-04 fixtures (`rt-01` … `rt-05`) round-trip through the
  relational schema and `project_document()` with byte-identical canonical
  output after normalising optional null keys.
- Configuration digests match `contracts/reference/task04/fixtures/digests.json`
  exactly:
  - rt-01 `b0837374…a14e5e`
  - rt-02 `5ee66c67…57f2eb`
  - rt-03 `a9c2e47d…6ec930`
  - rt-04 `ba18d012…bd4642`
  - rt-05 `96418a28…d89d31`
- Frozen snapshots (`capture_snapshot`) reproduce the same digest and
  `verify_snapshot` passes for every fixture.
- Ping result SHA-256 is recomputed from the stored canonical bytes and
  verified by a database trigger; mismatched values are rejected.
- `record_ping_result` and `record_error_envelope` validate documents against
  the frozen TASK-05 Draft 2020-12 schema before persistence; unknown fields
  and invalid nested shapes are rejected.

## Constraint verification

- Immutability guards reject UPDATE/DELETE on historical tables outside purge
  mode.
- Interface occupancy, switch management IP, router-only static routes,
  host-only default gateways, revision gaplessness, snapshot revision
  consistency, Ping endpoint eligibility, Ping result/command identity and
  error/snapshot project consistency are all enforced by triggers and covered
  by tests.

## Atomicity verification

- A simulated persistence failure rolls back the whole transaction; the prior
  committed revision and device set are unchanged.
- A duplicate device name raises `IntegrityConflictError` and leaves the
  revision count unchanged.

## Retrieval consistency

- `open_project` locks the project row in SHARE mode before reading any child
  table, so concurrent mutations cannot interleave.
- Snapshot capture locks the project row in UPDATE mode and records the exact
  current revisions.

## Conclusion

TASK-06 is implemented and verified against the TASK-04/TASK-05 contracts and
the DoD (atomicity, persistence failure preserves prior state, consistent
retrieval for AI/simulation, retention, deletion confirmation, immutable
evidence).
