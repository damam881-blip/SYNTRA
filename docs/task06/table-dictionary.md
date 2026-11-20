# Table Dictionary — TASK-06

All identifiers are UUIDv7 unless noted.  Timestamps are `timestamptz` (UTC).
IPv4 columns are `bigint` uint32 (T4-DEC-02).  Enum columns are PostgreSQL
native enums created once and shared.

## Topology / configuration (TASK-04)

### `project`
| Column | Type | Null | Notes |
|---|---|---|---|
| project_id | uuid PK | no | UUIDv7 |
| name | varchar(64) | no | trimmed, non-blank |
| description | varchar(2000) | yes | |
| state_revision | bigint | no | ≥ 1, monotonic |
| simulation_revision | bigint | no | ≤ state_revision |
| next_device_sequence | bigint | no | ≥ 1 |
| next_mac_sequence | bigint | no | ≥ 1 |
| next_connection_sequence | bigint | no | ≥ 1 |
| created_at | timestamptz | no | |
| updated_at | timestamptz | no | trigger-maintained |

### `project_revision`
Composite PK `(project_id, revision)`.  Append-only (immutability guard).
| Column | Type | Null | Notes |
|---|---|---|---|
| project_id | uuid FK project | no | cascade |
| revision | bigint | no | gapless per project |
| change_class | change_class | no | |
| change_kinds | varchar(32)[] | no | non-empty, approved values |
| affected_entity_ids | uuid[] | no | |
| committed_at | timestamptz | no | |

### `checkpoint`
| Column | Type | Null | Notes |
|---|---|---|---|
| checkpoint_id | uuid PK | no | |
| project_id | uuid FK project | no | cascade |
| revision | bigint | no | composite FK to project_revision |
| label | varchar(120) | yes | |
| created_at | timestamptz | no | |

### `device`
| Column | Type | Null | Notes |
|---|---|---|---|
| device_id | uuid PK | no | |
| project_id | uuid FK project | no | cascade |
| kind | device_kind | no | |
| display_name | varchar(64) | no | |
| normalized_name | text | no | project-unique |
| device_sequence | bigint | no | project-unique |
| default_gateway_ipv4 | bigint | yes | host-only (PC/SERVER) |
| position_x/y/z | double | no | presentation |
| rotation_y_degrees | double | no | [-180,180) |
| next_route_sequence | bigint | yes | router-only |
| created_at | timestamptz | no | |

### `interface`
| Column | Type | Null | Notes |
|---|---|---|---|
| interface_id | uuid PK | no | |
| project_id | uuid FK project | no | cascade |
| device_id | uuid | no | composite FK to device |
| display_name | varchar(32) | no | fixed inventory name |
| ordinal | smallint | no | 0..7 |
| interface_kind | interface_kind | no | |
| admin_state | admin_state | no | |
| mac_address | varchar(17) | no | project-unique, canonical |
| mac_sequence | bigint | no | |
| ipv4_address | bigint | yes | uint32 |
| ipv4_prefix_length | smallint | yes | 1..30, paired with address |

### `connection`
| Column | Type | Null | Notes |
|---|---|---|---|
| connection_id | uuid PK | no | |
| project_id | uuid FK project | no | cascade |
| interface_a_id | uuid | no | composite FK interface, a < b |
| interface_b_id | uuid | no | |
| cable_type | cable_type | no | |
| connection_sequence | bigint | no | project-unique |
| created_at | timestamptz | no | |

### `static_route`
| Column | Type | Null | Notes |
|---|---|---|---|
| route_id | uuid PK | no | |
| project_id | uuid FK project | no | cascade |
| router_device_id | uuid | no | composite FK device (router only) |
| destination_network | bigint | no | uint32, host bits zero |
| prefix_length | smallint | no | 0..32 |
| next_hop_ipv4 | bigint | no | uint32 |
| route_sequence | bigint | no | router-unique |
| created_at | timestamptz | no | |

## Simulation contract (TASK-05)

### `snapshot_ref`
| Column | Type | Null | Notes |
|---|---|---|---|
| snapshot_id | uuid PK | no | |
| project_id | uuid FK project | no | cascade |
| base_state_revision | bigint | no | must equal project state at capture |
| base_simulation_revision | bigint | no | ≤ base_state_revision |
| schema_version | varchar(16) | no | `1.0.0` |
| configuration_digest | varchar(64) | no | SHA-256 hex |
| configuration_json | jsonb | no | frozen projection |
| canonical_json | text | no | exact bytes hashed |
| created_at | timestamptz | no | |

### `ping_test_command`
| Column | Type | Null | Notes |
|---|---|---|---|
| command_id | uuid PK | no | |
| contract_version | varchar(16) | no | `1.0.0` |
| test_id | uuid | no | unique |
| project_id | uuid FK project | no | cascade |
| source_device_id | uuid | no | PC/SERVER only (trigger) |
| destination_device_id | uuid | no | PC/SERVER only (trigger) |
| test_kind | varchar(10) | no | `PING` |
| expected_echo_requests | smallint | no | 4 |
| initial_runtime_state | varchar(20) | no | `FRESH` |
| snapshot_id | uuid | no | composite FK snapshot |
| created_at | timestamptz | no | |

### `ping_test_result`
| Column | Type | Null | Notes |
|---|---|---|---|
| test_id | uuid PK | no | FK command |
| contract_version | varchar(16) | no | |
| project_id | uuid FK project | no | cascade |
| source_device_id | uuid | no | must match command |
| destination_device_id | uuid | no | must match command |
| snapshot_id | uuid | no | must match command |
| lifecycle | varchar(20) | no | `CLOSED` |
| execution_status | execution_status | no | |
| aggregate_outcome | aggregate_outcome | yes | |
| observation_status | observation_status | no | |
| started_at_ns … closed_at_ns | bigint | no | ≥ 0 |
| statistics_json | jsonb | no | object |
| request_results_json | jsonb | no | array ≤ 4 |
| diagnostics_json | jsonb | no | array |
| events_json | jsonb | no | array ≤ 40000 |
| hop_evidence_json | jsonb | no | array |
| derived_warning_evidence_json | jsonb | no | array |
| canonical_json | text | no | exact bytes |
| result_sha256 | varchar(64) | no | SHA-256 hex |
| created_at | timestamptz | no | |

### `error_envelope`
| Column | Type | Null | Notes |
|---|---|---|---|
| error_id | uuid PK | no | |
| contract_version | varchar(16) | no | |
| project_id | uuid FK project | yes | cascade |
| test_id | uuid FK ping_test_command | yes | no action |
| error_class | error_class | no | |
| code | error_reason | no | class/code consistent (check) |
| message_key | varchar(128) | no | |
| details_json | jsonb | no | array |
| snapshot_id | uuid | yes | trigger-validated against project |
| retryable | boolean | no | |
| canonical_json | text | no | exact bytes |
| canonical_sha256 | varchar(64) | no | SHA-256 hex |
| created_at | timestamptz | no | |

## Logs and retention

### `action_log`
Append-only (no UPDATE).  `revision` composite FK to project_revision.
| Column | Type | Null | Notes |
|---|---|---|---|
| log_id | uuid PK | no | |
| project_id | uuid FK project | no | cascade |
| actor | varchar(128) | no | default `system` |
| action_kind | varchar(64) | no | |
| entity_type | varchar(32) | yes | |
| entity_id | uuid | yes | |
| revision | bigint | yes | |
| detail_json | jsonb | no | object |
| created_at | timestamptz | no | indexed |

### `ping_log`
Append-only (no UPDATE).
| Column | Type | Null | Notes |
|---|---|---|---|
| log_id | uuid PK | no | |
| project_id | uuid FK project | no | cascade |
| test_id | uuid | no | composite FK command |
| snapshot_id | uuid | no | composite FK snapshot |
| aggregate_outcome | aggregate_outcome | yes | |
| execution_status | execution_status | no | |
| created_at | timestamptz | no | indexed |

### `error_log`
Append-only (no UPDATE).  Consistency with envelope enforced by trigger.
| Column | Type | Null | Notes |
|---|---|---|---|
| log_id | uuid PK | no | |
| project_id | uuid FK project | yes | |
| error_id | uuid FK error_envelope | no | cascade |
| error_class | error_class | no | |
| code | error_reason | no | |
| message_key | varchar(128) | no | |
| created_at | timestamptz | no | indexed |

### `retention_policy`
| Column | Type | Null | Notes |
|---|---|---|---|
| policy_name | varchar(32) PK | no | default row `default` |
| action_log_retention_days | int | no | 90 |
| ping_log_retention_days | int | no | 365 |
| error_log_retention_days | int | no | 365 |
| ping_result_retention_days | int | no | 365 |
| snapshot_retention_days | int | no | 365 |
| updated_at | timestamptz | no | trigger-maintained |

## Deletion audit

### `project_tombstone`
Immutable (no UPDATE/DELETE outside purge mode).
| Column | Type | Null | Notes |
|---|---|---|---|
| project_id | uuid PK | no | no FK; survives purge |
| project_name | varchar(64) | no | |
| last_state_revision | bigint | no | |
| last_simulation_revision | bigint | no | ≤ last_state_revision |
| deleted_by | varchar(128) | no | default `system` |
| deleted_at | timestamptz | no | |
