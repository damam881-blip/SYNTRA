# Real Ping Runner — Phase 1: Boundary and Replay Input Adapter

| Field | Value |
|---|---|
| Work item | Real `PingRunner` before TASK-07 §14.2 step 7 |
| Phase | 1 of 4 (approved plan: boundary → result assembler → event-driven core → end-to-end proof + D7-10) |
| Status | **IMPLEMENTED AND VERIFIED** |
| Date | 2026-11-23 |
| Authorization | Owner selected “اعتماد الخطة والبدء بالمرحلة 1” after the scoped plan was presented |
| Verification | `549 passed in 87.41s` (522 prior + 27 new tests); `ruff check` and `ruff format --check` clean across `app` and `tests` |
| Not included | Result assembler, simulation core, step-7 Ping endpoints, any persisted result |

## 1. Why this phase exists

The repository has every low-level simulation primitive (routing decisions, ARP resolution/cache, ICMP messages/correlator, Ethernet switching, discrete event queue) but **no orchestration**: `app/engine/ping/` and `app/modules/simulation/` were empty and no test chained ARP + routing + ICMP + frame forwarding. A real Ping result therefore cannot be produced by the API layer alone; the runner must first exist as a pure engine component.

Two contract constraints shaped the design:

1. **Replay input is a projection, not the full document.** `replay_input(snapshot)` verifies the snapshot digest and returns `{snapshot_id, base_*_revision, schema_version, configuration_digest, configuration}`, where `configuration` is the TASK-04 §7.4 behavioural projection. `project_from_fixture()` needs the full canonical document (names, positions, timestamps, revision array), so it cannot consume replay input directly.
2. **Engine purity is enforced.** `tests/unit/test_engine_boundaries.py` forbids `app.db`, `app.modules`, `app.core` and HTTP/ORM imports anywhere under `app/engine`. The runner must remain a `dict → dict` component, matching the §8.2 port that forbids database writes and topology changes.

## 2. Files added

| File | Purpose |
|---|---|
| `app/engine/ping/protocol.py` | `PingRunner` `@runtime_checkable` Protocol with the exact §8.2 signature; `PingRunnerInput`/`PingRunnerResult` aliases; **no implementation** |
| `app/engine/ping/topology.py` | `parse_replay_input` + `ReplaySnapshot` (identity validation) and `topology_from_replay_input` (projection → immutable engine `Project`) |
| `app/engine/ping/__init__.py` | Public re-exports of the boundary and adapter |
| `tests/unit/engine/test_ping_protocol.py` | 3 tests: exact signature, structural runtime check, no persistence methods |
| `tests/unit/engine/test_ping_topology.py` | 24 tests: all 5 TASK-04 fixtures, determinism, empty projection, 11 malformed inputs, bad interface owner and bad inventory slot |
| `docs/task07/PING-RUNNER-01_boundary-and-adapter.md` | This record |

## 3. The approved boundary (for D7-10)

```python
class PingRunner(Protocol):
    def run(
        self,
        replay_input: dict[str, object], *,
        test_id: UUID,
        project_id: UUID,
        source_device_id: UUID,
        destination_device_id: UUID,
    ) -> dict[str, object]: ...
```

The runner receives the verified replay snapshot plus the four identities of the accepted command. It returns one complete TASK-05 `PingTestResult` document. It never writes to PostgreSQL, never mutates the topology and never reads wall-clock time. The concrete implementation will be `SimulatedPingRunner` in phase 3; this phase deliberately ships **no** runner implementation, so no result can be produced or faked yet.

## 4. Adapter behavior and decisions

1. **Fail closed:** validates `schema_version == "1.0.0"`, lowercase UUIDv7 ids, lowercase SHA-256 digest, positive base revisions with `base_simulation_revision <= base_state_revision`, and presence/shape of all four configuration arrays. Malformed input raises `InvalidReplayInputError`.
2. **Preserves all simulation-relevant values:** device/interface/connection/route ids, kinds, sequences, admin states, MAC allocations, IPv4 configuration, gateways, cable types and L2 membership are copied from the frozen projection. Tests compare them against `project_from_fixture` for `rt-01`…`rt-05`, including derived L2 domains and interface operational states.
3. **Synthesises only presentation metadata:** because the projection omits it, device display names are derived as `{kind}-{sequence:02d}`, positions are `(0,0,0)`, timestamps are empty strings, and revision/checkpoint/snapshot arrays are empty (which also bypasses the full-document revision consistency check). A test asserts these values are deterministic. **None of them is copied into any TASK-05 event, diagnostic, hop or result field** — phase 2 will enforce that at the result builder boundary.
4. **Router next-sequence recovery:** `next_route_sequence` is not in the projection; it is rebuilt as `max(owned route_sequence) + 1` (or 1). This value is engine bookkeeping only and has no wire representation.
5. **Output is canonicalised** via `canonical_project`, so ordering is independent of projection input order. Repeated adaptation of equal input yields an equal `Project`.

## 5. Verification detail

- Protocol (3): exact parameter names/kinds and `dict[str, object]` return annotation; a conforming class satisfies the runtime protocol while a class without `run` does not; no `commit`/`session` members exist on the port.
- Topology (24): for every TASK-04 fixture, identity/revisions, device/interface/connection/route signatures and derived L2/operational views match `project_from_fixture`; repeated and deep-copied inputs produce equal projects; synthesized names/positions/timestamps are deterministic; an empty projection is accepted; 11 malformed identities/shapes are rejected; an interface referencing an unknown device and an invalid inventory slot are rejected.
- The pre-existing engine-boundary test still passes, confirming the new engine files introduced no forbidden imports.
- Full suite: **549 passed in 87.41s**; no pre-existing test regressed.
- Frozen artifacts (`contracts/reference/**`), the continuation package and original DOCX files were read only. No commit, push or PR action in this phase.

## 6. Next phase (requires the owner's go-ahead)

Phase 2 — `app/engine/ping/result.py`: build schema-valid, semantically self-consistent TASK-05 result documents (statistics rounding, aggregate outcome, request/diagnostic/event/hop correlation, self-ping case). Every generated document will be checked against the frozen JSON Schema **and** `verify_contract.py::check()`; reference examples are oracles only, never emitted as results.
