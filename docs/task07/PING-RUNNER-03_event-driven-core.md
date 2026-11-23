# Real Ping Runner — Phase 3: Event-Driven Simulation Core

| Field | Value |
|---|---|
| Work item | Real `PingRunner` before TASK-07 §14.2 step 7 |
| Phase | 3 of 4 (boundary → result assembler → **event-driven core** → end-to-end proof + D7-10) |
| Status | **IMPLEMENTED AND VERIFIED** |
| Date | 2026-11-23 |
| Authorization | Owner selected “انتقل للمرحلة 3: نواة المحاكاة (موصى به)” after phase 2 was reported |
| Verification | `579 passed in 94.81s` (565 prior + 14 new); `ruff check` and `ruff format --check` clean across `app` and `tests` |
| Not included | Step-7 Ping endpoints, any persisted result, any API-visible runner, final D7-10 decision record |

## 1. What was built

`app/engine/ping/runner.py` adds `SimulatedPingRunner`, the concrete implementation of the approved TASK-07 §8.2 `PingRunner` port. It is exported from `app.engine.ping`.

`run(replay_input, test_id, project_id, source_device_id, destination_device_id)`:

1. validates and adapts the frozen §7.4 replay projection through `topology_from_replay_input` (phase 1);
2. builds a per-run, isolated runtime view of devices, interfaces, operational states, cable peers, switch ports, ARP caches, switch MAC tables and router forwarding tables;
3. drives four real echo requests on the deterministic TASK-03 `EventQueue`;
4. converts the observed evidence into `ResultEvidence` and returns `assemble_result(evidence)` (phase 2).

The runner is pure `dict → dict`: no database, API, wall-clock time or topology mutation. It imports only TASK-03/04 engine primitives and the two earlier ping phases; the boundary test `tests/unit/test_engine_boundaries.py` still passes.

## 2. Engine primitives actually exercised

- **Scheduling:** `EventQueue` with integer nanoseconds, `(time, phase, creation_sequence)` ordering, request/test budgets and branch limits. Queue `creation_sequence`/`execution_index` start at 0, so emitted evidence indices are reassigned from 1 as required by the TASK-05 schema.
- **L2:** `EthernetFrame`, `SwitchMacTable.decide()` (source learning before forwarding), cable-peer traversal and TASK-03 propagation/transmission delays.
- **ARP:** `ArpResolutionContext` for a 200 ms resolution window with a single deadline, `ArpCache`, `arp_response_for` and accepted-reply application. Late, duplicate and unresolved evidence cannot reopen a finalized context.
- **L3:** `decide_host_forwarding` for endpoints and `RouterForwardingTable.decide` for routers, including connected/static route selection and TTL decrement.
- **ICMP:** `build_echo_request`, `EchoReplyCorrelator` and `icmp_error_allowed`; request/reply correlation uses the fixed ICMP identifier, sequence and both endpoint addresses.
- **Evidence:** only frozen TASK-05 `event_kind`/`direction`/`phase` values are emitted; `_emit` fails closed otherwise.

## 3. Evidence phase map (concrete)

The provisional phase wording in `PING-RUNNER-02_result-assembler.md` is replaced by the following simulation-owned mapping, to be ratified in `DEC-07-010_ping-runner-interface.md`:

| Phase | Name | Representative event kinds |
|---|---|---|
| `10` | Control | (request start is internal; no wire event) |
| `20` | Routing | `ROUTE_SELECTED`, `ROUTE_FAILED` |
| `30` | ARP | `ARP_REQUEST`, `ARP_REPLY`, `ARP_RESOLUTION` |
| `40` | Datapath | `FRAME_TX`, `FRAME_ARRIVED`, `FRAME_DROPPED`, `DEVICE_PROCESSED` |
| `50` | Failure/limit | `ICMP_ECHO_TIMEOUT`, `ICMP_ERROR_*`, `EXECUTION_LIMIT_REACHED`, `PENDING_EVENTS_CANCELLED` |
| `60` | Observation | `ICMP_ECHO_EMITTED`, `ICMP_ECHO_MATCHED`, `REQUEST_FINALIZED`, `TEST_FINALIZED`, `OBSERVATION_CLOSED`, `LOCAL_ECHO_PROCESSED` |

The assembler continues to validate only the schema enum; it does not infer phases.

## 4. Observable behaviour on the frozen fixtures

| Fixture | Simulated topology | Result | Dominant evidence |
|---|---|---|---|
| `rt-01` | PC — L2 switch — PC | `SUCCESS`, 4/4 | ARP, switched frames, matched replies, 24 physical hops |
| `rt-02` | PC — L2 switch — Server | `SUCCESS`, 4/4 | Same as `rt-01` with server endpoint |
| `rt-03` | PC — router — PC | `SUCCESS`, 4/4 | Host gateway ARP, router route selection, return-path gateway ARP |
| `rt-04` | PC — router — router — PC | `SUCCESS`, 4/4 | Two router hops each direction, static-route selection, 36 hops |
| `rt-05` | Same but no return static route | `FAILURE`, 0/4 | `NO_MATCHING_ROUTE` with `direction = RETURN` |

RTTs come only from emitted/received virtual times (e.g. `rt-04` average `667800 ns`); no reference example value is copied into generated results.

Additional verified scenarios: ARP with no responder (`ARP_NO_RESPONSE`), missing host gateway (`MISSING_DEFAULT_GATEWAY`), self-ping (`SUCCESS` with empty `hop_evidence`), echo timeout when the ARP window exceeds the request deadline (`ECHO_TIMEOUT`), controlled test-only fault injection for `PARTIAL_SUCCESS`, and `INCOMPLETE` with `REQUEST_EVENT_BUDGET_EXHAUSTED` at low event budgets. Repeated runs of the same replay input produce byte-identical documents.

## 5. Identity, hops and diagnostics

- ICMP identifier is `DEFAULT_ICMP_IDENTIFIER = 1234` for all four requests in every run; the logical UUID `test_id` is never used as an ICMP identifier.
- `RequestCorrelation.test_id` is set to that identifier, as required by the frozen correlator API.
- Frame and packet ids are generated from per-run deterministic counters and carried explicitly in `_FrameArrival`; no attribute is attached to slotted `EthernetFrame` objects.
- Physical hop evidence is derived only from witnessed `FRAME_TX`/`FRAME_ARRIVAL` pairs with the same frame id, direction and connection id; self-ping produces no hops.
- At most one primary diagnostic is created per request; non-success requests carry no match/RTT, and success requests carry no primary diagnostic.

## 6. Verification discipline

Every result produced by the runner in `tests/unit/engine/test_ping_runner.py` is checked twice:

1. `Draft202012Validator` against the frozen TASK-05 schema, loaded read-only;
2. `verify_contract.check()` from the frozen bundle, imported via `importlib.util` (never `run()`).

No file under `contracts/reference/**`, the continuation package or the original DOCX files was modified. Step 7 endpoints remain blocked.

## 7. Scope discipline and next step

No commit, push or PR action was performed in this phase; the owner's explicit request is still required. Phase 4 (needs a separate go-ahead) will produce the end-to-end proof and `docs/task07/DEC-07-010_ping-runner-interface.md` for owner approval before any step-7 implementation.
