# TASK-04 — Verification bundle v1.0.1

Standalone copy of the TASK-04 artifacts, so the checks can be re-run on the
exact files under review. These are the files listed in §15 of
`TASK-04 — Topology & Configuration Data Models.docx` (v1.0.1), plus this README,
a run script, the captured log and a checksum manifest.

The model is a data-model specification. These scripts verify **model
artifacts** — schema conformance, inventory, identifiers, addressing, caps,
revision arithmetic, the configuration digest, and the two accepted-with-warning
behaviours required by v1.0.1 §8.4. They do not execute, and make no claim
about, network behaviour; that belongs to TASK-01/02/03 acceptance.

## Contents

| File named in the review note | Path in this bundle |
| --- | --- |
| `topology-model-v1.schema.json` | `schemas/topology-model-v1.schema.json` |
| `rt-01.json` … `rt-05.json` | `fixtures/rt-01.json` … `fixtures/rt-05.json` |
| `check_model.py` | `tools/check_model.py` |
| `configuration_digest.py` | `tools/configuration_digest.py` |
| `make_fixtures.py` (supporting) | `tools/make_fixtures.py` |
| `digests.json` (supporting) | `fixtures/digests.json` |
| — | `tools/test_limits.py` (boundary suite), `README.md`, `verify.cmd`, `verify.sh`, `VERIFICATION.log`, `MANIFEST.sha256` |

The `schemas/` · `fixtures/` · `tools/` layout is required: both scripts resolve
their inputs relative to the parent of `tools/`. Keep the tree intact.

## Requirements

- Python 3.8 or newer (verified here on 3.13.5).
- `jsonschema` 4.x (`pip install jsonschema`), the only third-party dependency.
  `configuration_digest.py` needs no dependency at all.

## Run

Windows:

```
verify.cmd
```

Any platform:

```
python tools/check_model.py
python tools/configuration_digest.py --verify
python tools/test_limits.py
```

All three scripts exit `0` only when every assertion passes and non-zero
otherwise, so they can be wired into CI as-is. The exact output of a run on this
file set is in `VERIFICATION.log`: `checks run: 673`, the two self-tests, `PASS —
schema + model invariants satisfied for: rt-01.json, …, rt-05.json`, four `PASS`
lines from the digest verification with the reference digest
`ba18d012468c378746d93872281c15b4b5c132970a45e01f53657e3bbbd4642f`, then
`checks: 42   failed: 0` from the boundary suite.

## Correction applied for v1.0.1

The first bundle rejected two states that the reconciled model requires to be
accepted, so the checker was corrected before this bundle was built:

| State | Before | Now |
| --- | --- | --- |
| Duplicate IPv4 inside one L2 domain | failed as `duplicate IPv4 inside one L2 domain` | accepted; emits the derived `DUPLICATE_IPV4_L2_DOMAIN` warning (§6.4, §8.4) |
| `route_sequence` gap after deletion | failed as `route_sequence not contiguous` | accepted; sequences must be unique, immutable and below the allocation counter, but need not be contiguous (T4-DEC-09, §8.4) |
| Name trimming for `normalized_name` | used `str.strip()`, which also removes U+001C…U+001F | trims exactly the Unicode `White_Space` property, then NFC, then full casefold (§5.2, T4-CLOSE-02) |

Two invariants were kept and are still enforced: a duplicate `route_sequence`
within one router is rejected, and `next_route_sequence` must exceed every
allocated sequence. `check_model.py` proves the pair of corrections with two
self-tests over a mutated RT-04, so the acceptance is demonstrated on every run
rather than assumed.

## What the scripts cover

`tools/check_model.py` — layer 1 validates every fixture against the JSON Schema
with `jsonschema`; layer 2 re-derives the model independently and asserts the
invariants the schema cannot express. Per fixture:

- **Identity** — opaque UUIDv7-shaped ids, uniqueness of every id, immutable
  `device_sequence` / `connection_sequence` / `route_sequence`.
- **Referential integrity** — every `device_id`, `interface_id`,
  `router_device_id` and endpoint resolves; `rt-05` is asserted to be `rt-04`
  minus exactly one route, with a route set that is a proper subset.
- **Uniqueness** — normalized device names, port names and ordinals per device,
  MACs within a project, `mac_sequence` values.
- **Addressing** — host/network/broadcast alignment, approved exclusions, and
  duplicate detection inside one L2 domain as a warning rather than a failure.
- **Route sequence** — unique per router, positive, below the allocation
  counter; gaps permitted.
- **Inventory, caps and MDI** — exact port inventory per device kind, ≤ 30
  devices, ≤ 50 connections, MDI class matrix.
- **Revision** — gapless revisions from 1, `simulation_revision` equal to the
  last simulation-relevant commit, audit count equal to `state_revision`.

`tools/configuration_digest.py --verify` — recomputes the canonical projection
and proves it is behavioural rather than cosmetic: renaming a device, moving it
and renaming the project leave the digest unchanged; changing an address or an
admin state changes it; input array order is irrelevant.

`tools/make_fixtures.py` — regenerates all five fixtures deterministically.
Re-running it on this bundle reproduces `rt-01.json` … `rt-05.json` and
`digests.json` byte-for-byte; this was checked before the bundle was packaged.

`tools/test_limits.py` — 35 boundary checks on the values the reconciliation
fixed, each one asserting both sides of the boundary:

- `name` 64 accepted / 65 rejected, empty and whitespace-only rejected.
- `description` 2000 / 2001, `checkpoint.label` 120 / 121, `null` accepted on
  both.
- Caps: 30 / 31 devices, 50 / 51 connections.
- Host prefixes /1 and /30 accepted, /0, /31, /32 rejected; route prefixes /0
  and /32 accepted, /33 rejected.
- Name rule: ASCII, ideographic and no-break space trimming; casefold; sharp-s
  expansion; full-width is not folded by NFC + casefold alone; U+001C is not
  trimmed; a stale `normalized_name` is rejected.
- The two accepted-with-warning rules, and the two invariants that must still
  reject: duplicate `route_sequence` on one router, and a counter that does not
  exceed the allocated sequences.

## NAME-01 correction and regression protection

`DisplayName` is limited to 64 Unicode code points after Unicode White_Space
trimming and NFC normalization. `NormalizedName` is the complete, untruncated
Unicode full-casefold result and has **no 64-character bound**. This is the
approved representation correction (T4-VERIFY-FIX-01); it does not change the
upstream name comparison policy. The schema and backend/model checker must
reject a stale or truncated uniqueness key. `tools/test_limits.py` now contains
seven explicit NAME-01 regression assertions (including 40 × `ß` -> 80 `s`
characters, 65-character display rejection, and truncated-key rejection).


## Integrity

`MANIFEST.sha256` holds the SHA-256 of every shipped file:

```
sha256sum -c MANIFEST.sha256
```

or on Windows, compare against `Get-FileHash <file> -Algorithm SHA256`.

## Scope reminder

Passing these checks means the model is internally consistent, expressible and
correctly encoded, and that the two accepted-with-warning behaviours survive
validation. It does not mean any TASK-01/02/03 acceptance criterion has been
met. TASK-04 closure still requires reviewer sign-off on T4-C07-AC01..15 and a
Final Verification Report; nothing here self-certifies the task.

## Final acceptance coverage audit update

The final audit corrected the semantic checker to represent admin-disabled cabled interfaces, gaps in immutable allocation sequences after deletion, and router-separated L2 domains. Ten explicit regression checks were added to `tools/test_limits.py`. Latest verified counts: **666 model checks**, **52/52 regression/boundary tests**. The lower model-check count reflects removal of incorrect operational-link assertions, not an unchecked test failure. See `TASK-04_Final_Acceptance_Coverage_Audit.md` for downstream execution obligations.
