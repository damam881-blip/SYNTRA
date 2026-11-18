# TASK-05 — FINAL ACCEPTANCE COVERAGE AUDIT (APPROVED SCOPED BASELINE)

**Artifact:** TASK-05 Final Approved Reconstructed Contract Bundle, contract_version 1.0.0.
**Verification result:** 10/10 positive complete synthetic JSON examples accepted; 48/48 deliberately invalid mutations rejected; **58/58 PASS, 0 FAIL**. Includes nine new wire-vocabulary regression cases.
**Important:** This is a newly created reference schema, not the original absent files, and the synthetic fixtures are not simulator traces.

## Audited completion boundary

- **TASK-05 design decisions:** T5-CLOSE-01..08 approved by owner; T5-DEC-01..20 approved.
- **Wire vocabulary:** Frozen in `schemas/wire-vocabulary-v1.json` as TASK-05-owned reconstructed names; existing EventKind list and ErrorEnvelope.error_class list reconciled with explicit code/class mapping; typed EvidenceFacts remain a closed optional typed object. No invented facts are required.
- **Executable proof:** JSON Schema Draft 2020-12 and selected semantic consistency over synthetic data only; all 58 listed check statuses PASS.
- **T5-AC-01..40:** 3 VERIFIED_CONTRACT, 16 PARTIAL_CONTRACT, 21 NOT_EXECUTED; **not 40/40 passed**.
- **Outstanding engine:** RT-01..05, ARP/TTL/clock/matching, safety/horizon, causal event authenticity and replay determinism NOT EXECUTED.
- **Outstanding integrations:** Snapshot/digest authenticity and DB writes (TASK-06), HTTP/Unity/freshness/projections (TASK-07), AI grounding (TASK-08) NOT EXECUTED.
- **Earlier erroneous 59-check document:** Superseded. Previous executable reconstruction showed 49/49 (10+39); current frozen bundle shows 58/58 (10+48). Neither number is the original unavailable verifier's result.

## Acceptance-by-acceptance traceability

## Source acceptance matrix — all 40 cases

**Legend:** VERIFIED_CONTRACT = full testable contract assertion confirmed for a synthetic fixture; PARTIAL_CONTRACT = related contract property tested but actual scenario not run; NOT_EXECUTED = full engine/API/UI/AI scenario untested.

| Source AC | Scenario (source wording abbreviated) | Status | Next owner / missing evidence |
|---|---|---|---|
| T5-AC-01 | Accepted command; valid PC and Server IDs; compatible snapshot | PARTIAL_CONTRACT | TASK-05: contract-level proof; downstream integration remains |
| T5-AC-02 | Invalid UUID string in source_device_id | PARTIAL_CONTRACT | TASK-07: real request admission, trusted identity, API error mapping |
| T5-AC-03 | Destination is Router | NOT_EXECUTED | TASK-07: real request admission, trusted identity, API error mapping |
| T5-AC-04 | Unknown destination ID | PARTIAL_CONTRACT | TASK-07: real request admission, trusted identity, API error mapping |
| T5-AC-05 | Snapshot.project_id != command.project_id | PARTIAL_CONTRACT | TASK-07: real request admission, trusted identity, API error mapping |
| T5-AC-06 | Snapshot digest mismatch | NOT_EXECUTED | TASK-07: real request admission, trusted identity, API error mapping |
| T5-AC-07 | 4/4 success | PARTIAL_CONTRACT | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-08 | 1/4, 2/4, 3/4 success | PARTIAL_CONTRACT | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-09 | 0/4 success | PARTIAL_CONTRACT | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-10 | Source IPv4 missing | PARTIAL_CONTRACT | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-11 | Gateway off-link | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-12 | RT-05 PC1->PC2 | PARTIAL_CONTRACT | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-13 | RT-05 PC2->PC1 | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-14 | Two distinct valid ARP responders | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-15 | ARP safety-limited branch | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-16 | Reply processed exactly at deadline | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-17 | Reply physical arrival exactly at deadline but processing later | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-18 | Duplicate delivered Echo Requests | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-19 | TTL 1 + no route | NOT_EXECUTED | Simulator: verify upstream TTL-before-route precedence (do not assume from code names) |
| T5-AC-20 | ICMP error delivery fails | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-21 | Branch reaches 128 traversals | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-22 | Request event cap exhausted while unresolved | PARTIAL_CONTRACT | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-23 | Observation truncated after complete Ping | PARTIAL_CONTRACT | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-24 | Observation event exactly at horizon | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-25 | Frame cancelled before ingress | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-26 | Ping test repeated on same snapshot | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-27 | Presentation-only name change | NOT_EXECUTED | TASK-06/07: persistence, revision freshness, original snapshot |
| T5-AC-28 | Config change and revert | NOT_EXECUTED | TASK-06/07: persistence, revision freshness, original snapshot |
| T5-AC-29 | Local self-ping enabled host | PARTIAL_CONTRACT | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-30 | Two selected devices same IPv4 | NOT_EXECUTED | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-31 | Event array with reentrant phase | PARTIAL_CONTRACT | TASK-05: contract-level proof; downstream integration remains |
| T5-AC-32 | A diagnostic references unknown event ID | VERIFIED_CONTRACT | TASK-05: contract-level proof; downstream integration remains |
| T5-AC-33 | No Ethernet TX but local self-ping | PARTIAL_CONTRACT | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-34 | Zero logical packet emission | VERIFIED_CONTRACT | TASK-05: contract-level proof; downstream integration remains |
| T5-AC-35 | Wrong aggregate with all four successes | VERIFIED_CONTRACT | TASK-05: contract-level proof; downstream integration remains |
| T5-AC-36 | UI play-back altered speed | NOT_EXECUTED | TASK-07/Unity: playback contract integration |
| T5-AC-37 | AI consumer asks for explanation | NOT_EXECUTED | TASK-08/AI: grounded evidence consumption |
| T5-AC-38 | Missing return route but forward delivered | PARTIAL_CONTRACT | Simulator implementation: real causal event/RT/timing oracle |
| T5-AC-39 | Result after snapshot source unavailable | NOT_EXECUTED | TASK-06/07: persistence, revision freshness, original snapshot |
| T5-AC-40 | ErrorEnvelope contract under unsupported version | PARTIAL_CONTRACT | TASK-07: real request admission, trusted identity, API error mapping |

**Coverage count:** 3 VERIFIED_CONTRACT, 16 PARTIAL_CONTRACT, 21 NOT_EXECUTED = 40 mapped cases.

## T5-CLOSE-07 approved gate disposition

- **Contract Schema / Examples / Semantic tests:** PASS within the reconstructed reference set, 58/58.
- **Vocabulary closure:** PASS for defined reconstructed TASK-05 wire enum, strict optional EvidenceFacts, and explicit error code/class mapping; negative mutations exercised.
- **Snapshot and packet truth:** PARTIAL; real TASK-04 topology validation and true causal evidence require backend and simulator.
- **RT fixture execution, ARP timing, TTL/safety limits:** NOT EXECUTED; Simulation Engine owns execution oracles.
- **DB/HTTP/Unity/AI:** NOT EXECUTED; TASK-06/07/08 own integration.

**T5-C07-AC01..22 approval denotes acceptance of the verification plan, not successful execution of every downstream scenario.** The current 58 passing contract checks provide the complete evidence for this reconstructed static/semantic subset; the 40 source cases retain their individually scoped statuses above.

## Remaining implementation verification handoff

| Owner | Evidence still required |
|---|---|
| Simulation Engine | Real topology fixtures RT-01..05, deadline phase closure, ARP ambiguity/safety, TTL/root cause, loop/fanout, branch/event caps, event causal trace and determinism |
| TASK-06 | Trusted snapshot capture and digest recomputation, model identities/port references, transactional persistence, retention and immutable retrieval |
| TASK-07 | HTTP error mapping and authorization, version binding, stale revision comparison, full/subset trace completeness, Unity 3D movement and replay |
| TASK-08 | Read-only evidence explanations and prohibition on unsupported or invented network claims |

**Formal decision:** TASK-05 design and serialized reference contract **CLOSED/APPROVED within its scoped contract gate**. This does not certify engine/runtime or integration behavior. The reconstructed wire vocabulary is a TASK-05 contract-definition choice, not an assertion about an unavailable original artifact.
