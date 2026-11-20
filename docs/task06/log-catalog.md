# Log Catalog — TASK-06

## Action log (`action_log`)

Append-only, project-scoped, indexed by `(project_id, created_at)`.

| action_kind | Triggered by | entity_type |
|---|---|---|
| `PROJECT_CREATED` | `create_project` | project |
| `CHECKPOINT_SAVED` | `save_project` | checkpoint |
| `PROJECT_METADATA_UPDATED` | reserved | project |
| `DEVICE_ADDED` | `add_device` | device |
| `DEVICE_REMOVED` | `remove_device` | device |
| `DEVICE_RENAMED` | `rename_device` | device |
| `DEVICE_MOVED` | `move_device` / `rotate_device` | device |
| `INTERFACE_ADMIN_STATE_CHANGED` | `set_interface_admin_state` | interface |
| `INTERFACE_IPV4_CONFIGURED` | `configure_interface_ipv4` | interface |
| `INTERFACE_IPV4_CLEARED` | `clear_interface_ipv4` | interface |
| `HOST_GATEWAY_CONFIGURED` | `set_host_gateway` | device |
| `HOST_GATEWAY_CLEARED` | `clear_host_gateway` | device |
| `CONNECTION_ADDED` | `add_connection` | connection |
| `CONNECTION_REMOVED` | `remove_connection` | connection |
| `STATIC_ROUTE_ADDED` | `add_static_route` | static_route |
| `STATIC_ROUTE_EDITED` | `edit_static_route` | static_route |
| `STATIC_ROUTE_DELETED` | `delete_static_route` | static_route |
| `PING_COMMAND_ACCEPTED` | `accept_ping_command` | ping_test_command |
| `PING_RESULT_RECORDED` | `record_ping_result` | ping_test_result |
| `ERROR_RECORDED` | `record_error_envelope` | error_envelope |

`detail_json` is a JSON object with operation-specific fields (for example
`{"address": "192.168.10.10", "prefix_length": 24}`).

## Ping log (`ping_log`)

One row per recorded Ping result, written in the same transaction as the
immutable result.  Stores the aggregate outcome and execution status for fast
filtering; full evidence remains in `ping_test_result`.

## Error log (`error_log`)

One row per structured error envelope.  Mirrors `error_class`, `code` and
`message_key` so AI/simulation consumers can filter without parsing the
envelope.  `project_id` is nullable for project-less errors.

## Read views

- `v_ping_event` — one row per element of `events_json`.
- `v_ping_diagnostic` — one row per element of `diagnostics_json`.
- `v_ping_hop` — one row per element of `hop_evidence_json`.
- `v_ping_warning` — one row per element of `derived_warning_evidence_json`.

These views never duplicate storage; they are `CROSS JOIN LATERAL` projections.
