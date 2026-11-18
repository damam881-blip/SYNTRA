"""Boundary tests for the TASK-04 v1.0.1 values.

Covers the limits introduced by the reconciliation (T4-DEC-17: name 64,
description 2000, checkpoint label 120), the array caps, the host and route
prefix ranges, the Unicode name rule (T4-CLOSE-02) and the two
accepted-with-warning rules (duplicate IPv4, route_sequence gap).

Schema-only facts are checked with jsonschema; semantics are checked through
tools/check_model.py so the suite tests the shipped artifacts, not a copy.

Exit code 0 only when every check passes.
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(ROOT, "schemas", "topology-model-v1.schema.json")
FIXTURES = os.path.join(ROOT, "fixtures")

_spec = importlib.util.spec_from_file_location(
    "check_model", os.path.join(ROOT, "tools", "check_model.py")
)
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)

import jsonschema  # noqa: E402  (after the local import, keeps the error obvious)

SCHEMA_DOC = json.load(open(SCHEMA, encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA_DOC)

results = []
notes = []


def expect(label, ok, detail=""):
    results.append((label, bool(ok), detail))


def base(name="rt-04.json"):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


def schema_ok(doc):
    return not list(VALIDATOR.iter_errors(doc))


def uuid(n):
    return "0190a4c2-0900-7000-8000-%012d" % n


# ---------------------------------------------------------------- name bound
for length, should_pass in ((64, True), (65, False)):
    doc = base()
    doc["project"]["name"] = "A" * length
    expect(
        "project.name %d characters is %s" % (length, "accepted" if should_pass else "rejected"),
        schema_ok(doc) == should_pass,
    )

for text, label in (("", "empty name rejected"), ("   ", "whitespace-only name rejected")):
    doc = base()
    doc["project"]["name"] = text
    expect(label, not schema_ok(doc))

# --------------------------------------------------------- description bound
for length, should_pass in ((2000, True), (2001, False)):
    doc = base()
    doc["project"]["description"] = "B" * length
    expect(
        "project.description %d characters is %s" % (length, "accepted" if should_pass else "rejected"),
        schema_ok(doc) == should_pass,
    )

doc = base()
doc["project"]["description"] = None
expect("project.description null is accepted", schema_ok(doc))

# ------------------------------------------------------------ checkpoint label
for length, should_pass in ((120, True), (121, False)):
    doc = base()
    doc["checkpoints"] = [
        {
            "checkpoint_id": uuid(1),
            "revision": doc["project"]["state_revision"],
            "label": "C" * length,
            "created_at": doc["project"]["updated_at"],
        }
    ]
    if not should_pass:
        ok = not schema_ok(doc)
    else:
        ok = schema_ok(doc)
    expect(
        "checkpoint.label %d characters is %s" % (length, "accepted" if should_pass else "rejected"), ok
    )

doc = base()
doc["checkpoints"] = [
    {
        "checkpoint_id": uuid(2),
        "revision": doc["project"]["state_revision"],
        "label": None,
        "created_at": doc["project"]["updated_at"],
    }
]
expect("checkpoint.label null is accepted", schema_ok(doc))

# ------------------------------------------------------------------- caps
def with_devices(count):
    doc = base("rt-01.json")
    template = doc["devices"][0]
    doc["devices"] = []
    for i in range(count):
        d = json.loads(json.dumps(template))
        d["device_id"] = uuid(i + 1)
        d["device_sequence"] = i + 1
        d["display_name"] = "PC%d" % (i + 1)
        d["normalized_name"] = "pc%d" % (i + 1)
        doc["devices"].append(d)
    return doc


def with_connections(count):
    doc = base("rt-01.json")
    template = doc["connections"][0]
    doc["connections"] = []
    for i in range(count):
        c = json.loads(json.dumps(template))
        c["connection_id"] = uuid(i + 1)
        c["connection_sequence"] = i + 1
        doc["connections"].append(c)
    return doc


for count, should_pass in ((30, True), (31, False)):
    ok = schema_ok(with_devices(count))
    expect("devices cap: %d %s" % (count, "accepted" if should_pass else "rejected"), ok == should_pass)

for count, should_pass in ((50, True), (51, False)):
    ok = schema_ok(with_connections(count))
    expect(
        "connections cap: %d %s" % (count, "accepted" if should_pass else "rejected"), ok == should_pass
    )

# --------------------------------------------------------------- prefixes
def with_host_prefix(prefix):
    doc = base()
    iface = next(i for i in doc["interfaces"] if i.get("ipv4"))
    iface["ipv4"] = {"address": "192.168.10.10", "prefix_length": prefix}
    return doc


for prefix, should_pass in ((1, True), (30, True), (0, False), (31, False), (32, False)):
    ok = schema_ok(with_host_prefix(prefix))
    expect(
        "host prefix /%d %s" % (prefix, "accepted" if should_pass else "rejected"), ok == should_pass
    )


def with_route_prefix(prefix):
    doc = base()
    route = doc["static_routes"][0]
    route["destination_network"] = "0.0.0.0" if prefix == 0 else "203.0.113.0"
    route["prefix_length"] = prefix
    return doc


for prefix, should_pass in ((0, True), (32, True), (33, False)):
    ok = schema_ok(with_route_prefix(prefix))
    expect(
        "route prefix /%d %s" % (prefix, "accepted" if should_pass else "rejected"), ok == should_pass
    )

# ----------------------------------------------------------------- Unicode
cases = [
    ("  PC1  ", "pc1", "ASCII padding trimmed"),
    ("\u3000PC1\u3000", "pc1", "ideographic space is White_Space"),
    ("\u00a0PC1\u00a0", "pc1", "no-break space is White_Space"),
    ("PC1", "pc1", "casefolded to lower case"),
    ("Stra\u00dfe", "strasse", "casefold expands sharp s"),
]
for raw, want, label in cases:
    expect("name rule: " + label, cm.norm(raw) == want, "got %r" % cm.norm(raw))

expect(
    "name rule: full-width is not folded by NFC + casefold alone",
    cm.norm("\uff30\uff23\uff11") != "pc1",
    "got %r" % cm.norm("\uff30\uff23\uff11"),
)
expect(
    "name rule: U+001C is not White_Space and is not trimmed",
    cm.norm("\x1cPC1") == "\x1cpc1",
    "got %r" % cm.norm("\x1cPC1"),
)

# A stale normalized_name must still be rejected by the checker.
def stale_name(doc):
    doc["devices"][0]["normalized_name"] = doc["devices"][0]["display_name"].upper()


before = len(cm.failures)
cm.self_test("probe-stale-name", stale_name)
produced = cm.failures[before:]
del cm.failures[before:]
expect("stale normalized_name is rejected", bool(produced), produced[0] if produced else "")

# ------------------------------------------------ accepted-with-warning rules
before = len(cm.failures)
emitted = cm.self_test("duplicate-ipv4", cm.duplicate_ipv4)
produced = cm.failures[before:]
del cm.failures[before:]
expect("duplicate IPv4 in one L2 domain is accepted", not produced, produced[0] if produced else "")
expect(
    "duplicate IPv4 emits DUPLICATE_IPV4_L2_DOMAIN",
    any("DUPLICATE_IPV4_L2_DOMAIN" in w for w in emitted),
    str(emitted),
)

before = len(cm.failures)
cm.self_test("route-gap", cm.route_sequence_gap)
produced = cm.failures[before:]
del cm.failures[before:]
expect("route_sequence gap after deletion is accepted", not produced, produced[0] if produced else "")


def duplicate_sequence(doc):
    routes = doc["static_routes"]
    routes[1]["router_device_id"] = routes[0]["router_device_id"]
    routes[1]["route_sequence"] = routes[0]["route_sequence"]
    routes[1]["destination_network"] = "203.0.113.0"


before = len(cm.failures)
cm.self_test("dup-sequence", duplicate_sequence)
produced = cm.failures[before:]
del cm.failures[before:]
expect("duplicate route_sequence on one router is rejected", bool(produced), produced[0] if produced else "")


def counter_too_low(doc):
    route = doc["static_routes"][0]
    router = next(d for d in doc["devices"] if d["device_id"] == route["router_device_id"])
    router["next_route_sequence"] = route["route_sequence"]


before = len(cm.failures)
cm.self_test("counter-low", counter_too_low)
produced = cm.failures[before:]
del cm.failures[before:]
expect(
    "next_route_sequence that does not exceed allocations is rejected",
    bool(produced),
    produced[0] if produced else "",
)

# ------------------------------------------------ NAME-01 regression assertions
# Casefold may expand the length of the persisted-derived uniqueness key.
# The display-name bound applies to display_name only, not normalized_name.
long_name = "\u00df" * 40  # 40 Unicode code points -> 80 after full casefold
expanded_key = cm.norm(long_name)
doc = base()
doc["devices"][0]["display_name"] = long_name
doc["devices"][0]["normalized_name"] = expanded_key
expect("NAME-01: 40 sharp-s display name is accepted", schema_ok(doc))
expect("NAME-01: expanded casefold key has 80 characters", len(expanded_key) == 80)
expect("NAME-01: full 80-character normalized key is accepted", schema_ok(doc))
expect("NAME-01: normalized key is preserved without truncation", doc["devices"][0]["normalized_name"] == cm.norm(doc["devices"][0]["display_name"]))
# The semantic checker must also accept the full canonical key.
pre = len(cm.failures)
cm.validate_document(doc, "regression/NAME-01")
found = cm.failures[pre:]
del cm.failures[pre:]
expect("NAME-01: model checker accepts the expanded key", not found, str(found[:2]))
# The visible name remains bounded and is never silently shortened.
invalid = base()
invalid["devices"][0]["display_name"] = "A" * 65
invalid["devices"][0]["normalized_name"] = "a" * 65
expect("NAME-01: display name of 65 chars is rejected", not schema_ok(invalid))
# A wrong/truncated key must be rejected even if it passes structural schema.
truncated = base()
truncated["devices"][0]["display_name"] = long_name
truncated["devices"][0]["normalized_name"] = expanded_key[:64]
pre = len(cm.failures)
cm.validate_document(truncated, "regression/NAME-01-truncated")
found = cm.failures[pre:]
del cm.failures[pre:]
expect("NAME-01: truncated normalized key is rejected by model checker", bool(found), str(found[:2]))

# --------------------------------------------- Final coverage audit regressions
import copy

def semantic_result(doc, label):
    start_fail, start_warn, start_checks = len(cm.failures), len(cm.warnings), cm.checks
    try:
        cm.validate_document(doc, label)
        errors = cm.failures[start_fail:]
        warns = cm.warnings[start_warn:]
        return errors, warns
    finally:
        del cm.failures[start_fail:]
        del cm.warnings[start_warn:]
        cm.checks = start_checks

# A cable is persisted even when its endpoint is administratively disabled.
doc = base()
doc["interfaces"][0]["admin_state"] = "DISABLED"
errors, _ = semantic_result(doc, "regression/admin-disabled")
expect("COVERAGE: admin-disabled cabled interface is representable", not errors, str(errors[:2]))

# Allocation counters must survive deletion; gaps are allowed for all sequences.
doc = base()
doc["devices"][0]["device_sequence"] = 25
doc["project"]["next_device_sequence"] = 26
errors, _ = semantic_result(doc, "regression/device-sequence-gap")
expect("COVERAGE: device_sequence gaps allowed after deletion", not errors, str(errors[:2]))
doc = base()
doc["connections"][0]["connection_sequence"] = 25
doc["project"]["next_connection_sequence"] = 26
errors, _ = semantic_result(doc, "regression/connection-sequence-gap")
expect("COVERAGE: connection_sequence gaps allowed after deletion", not errors, str(errors[:2]))
doc = base()
doc["project"]["next_mac_sequence"] += 5
errors, _ = semantic_result(doc, "regression/mac-counter-after-deletion")
expect("COVERAGE: MAC allocation counter may exceed max surviving allocation", not errors, str(errors[:2]))

# Router interfaces must be distinct L2 domains even where the router connects both LANs.
doc = base()
hosts = [i for i in doc["interfaces"] if i.get("ipv4") and i["ipv4"]["address"].startswith("192.168.")]
# PC2 adopts PC1's IP, but remains on a separate router-facing L2 segment.
hosts[-1]["ipv4"] = dict(hosts[0]["ipv4"])
errors, warns = semantic_result(doc, "regression/separate-router-l2")
expect("COVERAGE: same IPv4 across router-isolated L2 domains accepted", not errors, str(errors[:2]))
expect("COVERAGE: no false duplicate warning across router", not any("DUPLICATE_IPV4_L2_DOMAIN" in w for w in warns), str(warns))

# Duplicate address across an actual link must still be detected as a warning.
doc = base()
transit = [i for i in doc["interfaces"] if i.get("ipv4") and i["ipv4"]["address"].startswith("10.0.12.")]
transit[1]["ipv4"] = dict(transit[0]["ipv4"])
errors, warns = semantic_result(doc, "regression/transit-duplicate")
expect("COVERAGE: duplicate IPv4 on same L2 accepted", not errors, str(errors[:2]))
expect("COVERAGE: duplicate IPv4 on same L2 warns", any("DUPLICATE_IPV4_L2_DOMAIN" in w for w in warns))

# An interface that is an A endpoint in one row cannot be B in another.
doc = base()
existing = doc["connections"][0]
other = doc["connections"][1]
# force overlap across opposite endpoint positions
other["interface_b_id"] = existing["interface_a_id"]
errors, _ = semantic_result(doc, "regression/cross-column-occupancy")
expect("COVERAGE: cross-column occupancy violation rejected", any("interface used by two connections" in e for e in errors), str(errors[:3]))

# A duplicated creation sequence is invalid even with a large allocation counter.
doc = base()
doc["connections"][1]["connection_sequence"] = doc["connections"][0]["connection_sequence"]
errors, _ = semantic_result(doc, "regression/duplicate-connection-sequence")
expect("COVERAGE: duplicate connection_sequence rejected", any("connection_sequence not unique" in e for e in errors), str(errors[:3]))

# ------------------------------------------------------------------- report
width = max(len(label) for label, _, _ in results)
failed = 0
for label, ok, detail in results:
    print(("PASS  " if ok else "FAIL  ") + label.ljust(width) + ("   " + detail if detail and not ok else ""))
    if not ok:
        failed += 1

print()
print("checks: %d   failed: %d" % (len(results), failed))
for note in notes:
    print("note:", note)
sys.exit(1 if failed else 0)
