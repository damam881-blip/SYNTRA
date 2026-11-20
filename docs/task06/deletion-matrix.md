# Deletion Matrix — TASK-06

Deletion is always confirmed by exact project name and runs inside one
transaction with `syntra.purge_mode = 'on'`.

| Entity | On project delete | On entity delete | Notes |
|---|---|---|---|
| project | deleted | n/a | root aggregate |
| device | cascade | removed | device removal also removes its interfaces, connections and static routes |
| interface | cascade | n/a | never deleted independently |
| connection | cascade | removed | occupancy trigger guards inserts only |
| static_route | cascade | removed | |
| project_revision | cascade (purge) | never | immutable; purge mode allows removal |
| checkpoint | cascade | never | immutable; removed with project |
| snapshot_ref | cascade (purge) | never | frozen evidence; purge mode allows removal |
| ping_test_command | cascade (purge) | never | immutable |
| ping_test_result | cascade (purge) | never | immutable |
| error_envelope | cascade | never | immutable; project-less envelopes survive |
| action_log | cascade | never | append-only, no UPDATE |
| ping_log | cascade | never | append-only, no UPDATE |
| error_log | cascade | never | append-only, no UPDATE |
| retention_policy | unaffected | n/a | global named policy |
| project_tombstone | inserted | never | survives the purge for audit |

## Retention (time-based)

| Table | Default days | Mechanism |
|---|---|---|
| action_log | 90 | `purge_expired` |
| ping_log | 365 | `purge_expired` |
| error_log | 365 | `purge_expired` |
| error_envelope | 365 | `purge_expired` |
| ping_test_result | 365 | `purge_expired` |
| snapshot_ref | 365 | `purge_expired` (cascades dependent commands/results/logs) |

Retention never removes projects, revisions of surviving projects, devices or
topology rows.  Retention of snapshots cascades to Ping commands, results and
Ping logs through their foreign keys.
