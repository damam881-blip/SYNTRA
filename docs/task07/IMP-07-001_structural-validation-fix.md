# Implementation Record IMP-07-001 — TASK-02 Structural Validation Wired into TASK-06 Services

| Field | Value |
|---|---|
| Record ID | IMP-07-001 |
| Status | **IMPLEMENTED AND VERIFIED** |
| Approval basis | Project owner explicitly approved implementation on 2026-11-23 ("نعم، نفّذ الآن (موصى به)"). |
| Date | 2026-11-23 |
| Classification | Non-blocking upstream implementation gap; not one of TASK-07 blocking points 1–5 |
| Ownership | TASK-02 §3.1A/NET-03 semantics; TASK-06 service enforcement; TASK-07 §7.4/§9.4 wording now truthful |
| Verification | `405 passed in 55.59s` (baseline 316 + 78 new unit + 11 new PostgreSQL integration tests); `ruff check` and `ruff format --check` clean |
| Frozen artifacts | Unchanged; no file under `contracts/reference/**`, no DOCX, no continuation package |

## 1. Problem closed

Two normative TASK-02 structural rules were documented and present in reference/engine helpers but were not enforced by the TASK-06 mutation services:

1. **MDI/MDI-X cable matrix** — `add_connection` checked only the `cable_type` enum, endpoint distinctness and membership; it never derived device MDI classes, so physically invalid links were stored.
2. **IPv4 exclusion policy** — `ipv4_to_int` checked only dotted-decimal syntax, while `configure_interface_ipv4`, `set_host_gateway` and `add_static_route` never invoked the engine's `host_address_problem`, `gateway_problem` or `next_hop_problem`. Excluded ranges, network/directed-broadcast addresses and limited broadcast were accepted.

## 2. Changes made

### New file — `app/modules/projects/validation.py`

Pure helpers, no simulation logic:

- `mdi_class(kind)` — PC/SERVER/ROUTER → `MDI`, L2_SWITCH → `MDI_X`.
- `cable_type_allowed(first_kind, second_kind, cable_type)` — TASK-04 matrix (`GENERIC_ETHERNET` always allowed; like↔like requires `CROSSOVER`, MDI↔MDI_X requires `STRAIGHT_THROUGH`).
- `validate_host_address(address, prefix_length)` — reuses `app.engine.ipv4.address.host_address_problem`; rejects excluded ranges, network/broadcast, limited broadcast and non-ASCII digits; raises `ContractValidationError` (§9.3 → 422).
- `validate_special_address(address, field, role)` — reuses `app.engine.ipv4.policy.gateway_problem` / `next_hop_problem`; off-link and self-referencing gateways remain storable with runtime warning, as TASK-02 requires.

### Modified — `app/modules/projects/service.py`

| Function | Added guard | Error |
|---|---|---|
| `add_connection` | derives both device kinds, validates the MDI/cable matrix before any write | `IntegrityConflictError` (§9.3 → 409) |
| `configure_interface_ipv4` | `validate_host_address` before conversion | `ContractValidationError` (422) |
| `set_host_gateway` | `validate_special_address(..., role="gateway")` | `ContractValidationError` (422) |
| `add_static_route` | `validate_special_address(..., role="next_hop")`; `0.0.0.0/0` destination still valid | `ContractValidationError` (422) |

All guards execute after the project row is locked and before mutation, so rejection advances no revision and commits nothing.

### Tests

- `tests/unit/test_project_validation.py` — 78 tests: 4 MDI classes, all 36 kind-pair/cable combinations, excluded ranges, network/broadcast, default-allow ranges, non-ASCII digits, gateway/next-hop roles.
- `tests/integration/db/test_mutation_validation.py` — 11 PostgreSQL-backed tests: incompatible cable rejected with no connection row and no revision advance, compatible/generic cables accepted, invalid host addresses rejected with no configuration change, limited-broadcast gateway rejected, excluded next hop rejected while a valid default route is accepted.

## 3. Acceptance evidence

- Baseline preserved: all pre-existing 316 tests still pass.
- New total: **405 passed in 55.59s**.
- Lint/format: clean for all changed Python files.
- Frozen reference artifacts byte-identical; `git status` shows only the service modification and new untracked validation/tests/docs files.

## 4. Boundaries

- No Task 7 API router, Pydantic envelope, ETag guard, Ping adapter or OpenAPI snapshot was added by this record.
- No commit, branch or PR was created.
- The TASK-07 draft §7.4/§9.4 wording is now accurate without amendment; no DOCX was edited.
