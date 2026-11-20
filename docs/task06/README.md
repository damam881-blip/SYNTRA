# TASK-06 — PostgreSQL, Project Lifecycle & Log Policy

This directory contains the audit artifacts for TASK-06 as implemented in
`E:\SYNTRA\network-simulator-backend`.  The implementation lives under
`app/db`, `app/modules/projects` and `app/modules/logs`; the Alembic
migration is `migrations/versions/0001_initial.py`.

| Artifact | File |
|---|---|
| Entity relationship diagram | [`erd.md`](erd.md) |
| Table dictionary | [`table-dictionary.md`](table-dictionary.md) |
| Transaction policy | [`transaction-policy.md`](transaction-policy.md) |
| Migration plan | [`migration-plan.md`](migration-plan.md) |
| Deletion matrix | [`deletion-matrix.md`](deletion-matrix.md) |
| Log catalog | [`log-catalog.md`](log-catalog.md) |
| Sample project lifecycle | [`sample-lifecycle.md`](sample-lifecycle.md) |
| Verification report | [`verification.md`](verification.md) |

## Implementation summary

- PostgreSQL 13+ (tested on 16.2) via SQLAlchemy 2.1 + psycopg 3.
- 16 tables: 7 TASK-04 topology/configuration, 4 TASK-05 simulation contract,
  4 log/retention tables, 1 deletion-audit tombstone.
- UUIDv7 primary keys, IPv4 stored as `bigint` (uint32, T4-DEC-02), canonical
  enum types shared across tables.
- Cross-row invariants enforced by triggers: interface occupancy, router-only
  static routes, switch management-IP prohibition, host-only default gateways,
  revision gaplessness, snapshot revision consistency, Ping endpoint eligibility,
  Ping result/command identity, canonical JSON SHA-256, error/snapshot project
  consistency, immutability guards, retention policy.
- Read views `v_ping_event`, `v_ping_diagnostic`, `v_ping_hop`, `v_ping_warning`
  expose TASK-05 evidence arrays without duplicating storage.
- Real PostgreSQL integration suite: 33 tests (schema, constraints,
  lifecycle, atomicity, snapshot digests, evidence, retention).
