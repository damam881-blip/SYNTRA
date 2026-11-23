# Real Ping Runner — Phase 2: TASK-05 Result Assembler

| Field | Value |
|---|---|
| Work item | Real `PingRunner` before TASK-07 §14.2 step 7 |
| Phase | 2 of 4 (boundary → **result assembler** → event-driven core → end-to-end proof + D7-10) |
| Status | **IMPLEMENTED AND VERIFIED** |
| Date | 2026-11-23 |
| Authorization | Owner selected “انتقل للمرحلة 2: مُجمّع النتيجة (موصى به)” after phase 1 was reported |
| Verification | `565 passed in 87.97s` (549 prior + 16 new); `ruff check` and `ruff format --check` clean across `app` and `tests` |
| Not included | Simulation core, step-7 Ping endpoints, any persisted result, any command-visible runner |

## 1. What was built

`app/engine/ping/result.py` is the single boundary that converts raw simulation observations into a complete TASK-05 `PingTestResult` document. It owns every derived field whose value is fixed by the frozen contract and it fail-closes on inconsistent evidence.

### Input model (evidence, not outcomes)

| Dataclass | Carries |
|---|---|
| `RequestEvidence` | outcome, started/finalized/emitted times, matched event id, primary diagnostic id, path statuses |
| `EventEvidence` | event id, virtual time, phase, kind, direction, execution/creation sequence, correlation ids, closed `facts` |
| `DiagnosticEvidence` | diagnostic id, code, classification, primary flag, request sequence, direction, detection point, trigger, completeness, `facts` |
| `HopEvidence` | hop id, packet/frame lineage, endpoints/interfaces/connection, timing, outcome, source event ids |
| `ResultEvidence` | 4 identities, `snapshot_ref`, execution/observation status, timestamps, ICMP identifier, all four collections |

The concrete event-driven core (phase 3) supplies these values from actual simulation. **No code path in this phase can produce a result without explicit evidence**; unit tests supply constructed observations purely as oracles, the same role the frozen TASK-05 examples play.

### Derived by the assembler

- **Identity/snapshot/envelope:** exact 19 required fields, `contract_version` and `schema_version` = `"1.0.0"`, `lifecycle = "CLOSED"`.
- **Per-request deadline:** `started_at_ns + 1_000_000_000`; **RTT:** `finalized_at_ns - emitted_at_ns` for successes only.
- **Statistics:** counters over request outcomes with the verifier's exact rounding — loss `None if sent == 0 else (2*10000*(sent-replies)//sent + 1)//2`; RTT average `(2*sum//n + 1)//2`; min/max/sum/`None` as applicable.
- **Aggregate outcome:** `SUCCESS` (4 replies), `PARTIAL_SUCCESS` (1–3), `FAILURE` (0), or `null` for `INCOMPLETE`.
- **Top-level timestamps:** `finalized_at_ns` = max request finalization; `closed_at_ns` defaults to it; ordering validated.

## 2. Fail-closed semantic validation

Before returning a document, `assemble_result` re-checks the same cross-field invariants enforced by `verify_contract.py::sem()` — so a result can never be persisted merely because it passed the JSON Schema:

- snapshot↔project identity and revision ordering;
- `COMPLETED` ⇒ exactly 4 requests, no `EXECUTION_LIMITED`, aggregate derived; `INCOMPLETE` ⇒ no aggregate and `observation_status = NOT_STARTED`;
- unique event/diagnostic/hop ids, unique and strictly increasing `execution_index`, unique `creation_sequence`, ≤ 40 000 events, non-decreasing virtual time;
- diagnostic trigger references, one primary per request sequence, primary references on requests;
- request deadline/time/emission/non-overlap rules;
- `SUCCESS` ⇒ matched `ICMP_ECHO_MATCHED` event at exactly `finalized_at_ns` with matching sequence, derived RTT, no primary diagnostic; non-success ⇒ no match/RTT; unique matched reply ids;
- hop event/diagnostic references, delivered-time and drop-cause rules, no `LOCAL` hops, empty hops for self-ping.

`ResultAssemblyError` is raised on any violation; no partial document is emitted.

## 3. Verification detail

Every assembled document in the tests is validated twice:

1. `Draft202012Validator` against the frozen `task05-contract-v1.schema.json` (loaded read-only).
2. `verify_contract.check()` from the frozen bundle via `importlib.util.spec_from_file_location` — the module is imported only; its `run()` (which rewrites the bundle report) is never called and no reference file is modified.

Scenarios: full success with witnessed frame TX/ARRIVAL hop evidence; partial success; complete failure (ARP and return-route variants); zero-sent with null loss; `INCOMPLETE` with an execution-limit diagnostic; self-ping with empty hops; half-up rounding at 25 % loss and 250 001 ns average; six deliberate inconsistencies (missing match event, non-monotonic execution index, dangling diagnostic trigger, wrong snapshot project, delivered hop without completion time, duplicate primary); self-ping with hops; `COMPLETED` with `EXECUTION_LIMITED`; absence of any synthesised presentation metadata in the serialized result; determinism of repeated assembly.

## 4. Contract decisions held for D7-10

- **ICMP identifier:** a single project-run constant stamped on all four requests (`DEFAULT_ICMP_IDENTIFIER = 1234`, matching the reference oracle). The engine does not derive it from wall-clock time or UUIDs; phase 3 will keep it constant per run for determinism.
- **Phase map:** evidence events carry the numeric `phase` supplied by the simulation. Phases 10/20/30/40/50/60 are reserved for ARP/route/forwarding/reply/lifecycle/observation stages; the concrete mapping will be fixed in phase 3 and recorded in `DEC-07-010_ping-runner-interface.md` before step 7. The assembler only validates that the value is in the schema enum.
- **No reference output is emitted:** the frozen examples are verification oracles only. The assembler cannot read them.

## 5. Scope discipline

Frozen artifacts (`contracts/reference/**`), the continuation package and original DOCX files were read only. No commit, push or PR action in this phase. TASK-07 step 7 endpoints remain blocked until the simulation core is proven end-to-end and D7-10 is approved.

## 6. Next phase (requires the owner's go-ahead)

Phase 3 — `app/engine/ping/runner.py`: concrete `SimulatedPingRunner` implementing the approved `PingRunner` port. It will drive four requests on the deterministic `EventQueue`, compose host/router forwarding, ARP resolution/cache, Ethernet switching, ICMP correlation and IPv4 TTL, and feed `ResultEvidence` to this assembler. Scenarios: direct, multi-hop, ARP no-response, no route, self-ping, timeout/partial, and `INCOMPLETE` at event budgets.
