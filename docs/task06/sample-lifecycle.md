# Sample Project Lifecycle — TASK-06

This walkthrough mirrors the smoke test in
`tests/integration/db/test_lifecycle.py`.

## 1. Create

```python
project = create_project(session, name="Smoke Lab", description="basic lifecycle")
# state_revision = 1, simulation_revision = 1
# project_revision 1: TOPOLOGY / [PROJECT_CREATED]
```

## 2. Add topology

```python
pc1 = add_device(session, project.project_id, kind="PC", display_name="PC1")
sw = add_device(session, project.project_id, kind="L2_SWITCH", display_name="SW1")
pc2 = add_device(session, project.project_id, kind="PC", display_name="PC2")
# each device allocates its inventory interfaces and MACs from the project counters
```

## 3. Configure

```python
configure_interface_ipv4(
    session, project.project_id, interface_id=pc1_if, address="192.168.10.10", prefix_length=24
)
configure_interface_ipv4(
    session, project.project_id, interface_id=pc2_if, address="192.168.10.20", prefix_length=24
)
set_host_gateway(session, project.project_id, device_id=pc1.device_id, gateway_ipv4="192.168.10.1")
add_connection(session, project.project_id, interface_a_id=pc1_if, interface_b_id=sw_if0)
add_connection(session, project.project_id, interface_a_id=pc2_if, interface_b_id=sw_if1)
```

Each call increments `state_revision` and `simulation_revision`, appends a
`project_revision` row and an `action_log` row.

## 4. Presentation change

```python
move_device(session, project.project_id, device_id=pc2.device_id, position=Position(9.0, 1.0, -2.0))
# state_revision += 1, simulation_revision unchanged
```

## 5. Save

```python
save_project(session, project.project_id, label="after topology")
# checkpoint at the current revision; no revision bump
```

## 6. Ping

```python
command = accept_ping_command(
    session, project.project_id, source_device_id=pc1.device_id, destination_device_id=pc2.device_id
)
# freezes a snapshot at the current revisions and stores its digest
record_ping_result(session, result_document)
# immutable result + ping_log row
```

## 7. Error

```python
record_error_envelope(
    session,
    {
        "error_class": "PERSISTENCE_FAILURE",
        "code": "PERSISTENCE_UNAVAILABLE",
        "message_key": "persistence.failed",
        "details": [{"x": 1}],
        "project_id": str(project.project_id),
    },
)
```

## 8. Delete

```python
tombstone = delete_project(session, project.project_id, confirm_name="Smoke Lab")
# tombstone written first; then the aggregate and all evidence are purged
# under syntra.purge_mode = 'on'
```

After deletion: `project` row gone, tombstone remains, `projects left = 0`.
