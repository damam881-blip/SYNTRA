"""Semantic checker for TASK-04 model documents and reference-topology fixtures.

Layer 1: JSON Schema validation of schemas/topology-model-v1.schema.json.
Layer 2: model invariants that JSON Schema cannot express (inventory, MAC
         derivation, address alignment, MDI matrix, revision gaplessness,
         cap enforcement, fixture equivalence RT-04 vs RT-05).

Reconciled rules (document v1.0.1, sections 8.4 and 6.4): a duplicate IPv4
inside one L2 domain is a configuration TASK-02 permits, so it MUST be accepted
as a derived DUPLICATE_IPV4_L2_DOMAIN warning rather than rejected, and a
route_sequence gap left by deletion MUST be accepted because sequences are
never renumbered. Both are proven by self-tests at the end of main().

Exit code 0 = every check passed. No third-party dependency except jsonschema
(pip install jsonschema); everything else is stdlib.
"""
import hashlib
import io
import ipaddress
import json
import os
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(ROOT, "schemas", "topology-model-v1.schema.json")
FIXTURES = os.path.join(ROOT, "fixtures")

DEVICE_KINDS = {"PC", "SERVER", "L2_SWITCH", "ROUTER"}
INVENTORY = {
    "PC": ["FastEthernet0"],
    "SERVER": ["FastEthernet0"],
    "L2_SWITCH": [f"FastEthernet0/{i}" for i in range(1, 7)]
    + ["GigabitEthernet0/1", "GigabitEthernet0/2"],
    "ROUTER": [
        "FastEthernet0/0",
        "FastEthernet0/1",
        "GigabitEthernet0/0",
        "GigabitEthernet0/1",
    ],
}
SPEED = {"FAST_ETHERNET": 100, "GIGABIT_ETHERNET": 1000}
MDI = {"PC": "MDI", "SERVER": "MDI", "ROUTER": "MDI", "L2_SWITCH": "MDI_X"}
CABLE_MATRIX = {
    ("MDI", "MDI"): {"GENERIC_ETHERNET", "CROSSOVER"},
    ("MDI", "MDI_X"): {"GENERIC_ETHERNET", "STRAIGHT_THROUGH"},
    ("MDI_X", "MDI_X"): {"GENERIC_ETHERNET", "CROSSOVER"},
}
EXCLUDED = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
]

failures = []
warnings = []
checks = 0


def check(cond, label):
    global checks
    checks += 1
    if not cond:
        failures.append(label)


def warn(text):
    """An accepted-but-noteworthy condition, e.g. a permitted duplicate address."""
    warnings.append(text)


def load(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# The White_Space property (PropList.txt). Python's str.strip() also removes
# U+001C..U+001F, which are not White_Space, so the trim is done explicitly.
WHITE_SPACE = {
    0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0x85, 0xA0, 0x1680,
    0x2028, 0x2029, 0x202F, 0x205F, 0x3000,
} | set(range(0x2000, 0x200B))


def norm(name):
    """§5.2: trim White_Space, normalize to NFC, then Unicode full casefold."""
    start, end = 0, len(name)
    while start < end and ord(name[start]) in WHITE_SPACE:
        start += 1
    while end > start and ord(name[end - 1]) in WHITE_SPACE:
        end -= 1
    return unicodedata.normalize("NFC", name[start:end]).casefold()


def mac_for(project_id, seq):
    salt = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:4]
    raw = f"02{salt}{seq:06x}"
    return ":".join(raw[i:i + 2] for i in range(0, 12, 2))


def host_role_ok(text, what, label):
    addr = ipaddress.ip_address(text)
    check(not any(addr in net for net in EXCLUDED), f"{label}: {what} {text} in excluded range")
    check(int(addr) != 0xFFFFFFFF, f"{label}: {what} is limited broadcast")


def check_interface_address(cfg, label):
    addr = ipaddress.ip_address(cfg["address"])
    network = ipaddress.ip_network(f"{cfg['address']}/{cfg['prefix_length']}", strict=False)
    host_role_ok(cfg["address"], "address", label)
    check(addr != network.network_address, f"{label}: address equals network address")
    check(addr != network.broadcast_address, f"{label}: address equals directed broadcast")
    check(1 <= cfg["prefix_length"] <= 30, f"{label}: host prefix outside /1../30")


def interface_states(doc):
    """Derived operational state: admin ENABLED and a committed link to an
    admin-ENABLED peer (T1-CFG-07 / VAL-34)."""
    by_id = {i["interface_id"]: i for i in doc["interfaces"]}
    peer = {}
    for c in doc["connections"]:
        peer[c["interface_a_id"]] = c["interface_b_id"]
        peer[c["interface_b_id"]] = c["interface_a_id"]
    states = {}
    for iid, iface in by_id.items():
        if iface["admin_state"] != "ENABLED":
            states[iid] = ("ADMIN_DISABLED", False, None)
            continue
        other = peer.get(iid)
        if other is None:
            states[iid] = ("NO_LINK", False, None)
            continue
        if by_id[other]["admin_state"] != "ENABLED":
            states[iid] = ("PEER_DISABLED", False, None)
            continue
        speed = min(SPEED[iface["interface_kind"]], SPEED[by_id[other]["interface_kind"]])
        states[iid] = ("OPERATIONAL", True, speed)
    return states, peer


def l2_domains(doc):
    """L2 broadcast domains are formed by cable links and switch internal
    bridging, NEVER by joining all interfaces of a router. Routers separate
    L2 domains even when forwarding IPv4 between those domains.
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    devices = {d["device_id"]: d for d in doc["devices"]}
    by_iface = {i["interface_id"]: i for i in doc["interfaces"]}
    for iid in by_iface:
        find(iid)
    switch_ports = {}
    for i in doc["interfaces"]:
        if devices[i["device_id"]]["kind"] == "L2_SWITCH":
            switch_ports.setdefault(i["device_id"], []).append(i["interface_id"])
    for ids in switch_ports.values():
        for iid in ids[1:]:
            union(ids[0], iid)
    for c in doc["connections"]:
        union(c["interface_a_id"], c["interface_b_id"])
    domains = {}
    for iid in by_iface:
        domains.setdefault(find(iid), []).append(iid)
    return list(domains.values())


def validate_document(doc, label):
    schema = load(SCHEMA)
    try:
        import jsonschema

        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
        check(not errors, f"{label}: schema violations: {[e.message for e in errors][:3]}")
    except ImportError:
        check(False, "jsonschema is not installed (pip install jsonschema)")

    project = doc["project"]
    devices = doc["devices"]
    interfaces = doc["interfaces"]
    connections = doc["connections"]
    routes = doc["static_routes"]

    check(project["state_revision"] == len(doc["revisions"]), f"{label}: revision count mismatch")
    for n, rev in enumerate(doc["revisions"], start=1):
        check(rev["revision"] == n, f"{label}: revision {n} not gapless")
    check(
        project["simulation_revision"]
        == max(
            r["revision"]
            for r in doc["revisions"]
            if r["change_class"] in {"TOPOLOGY", "CONFIGURATION", "MIXED"}
        ),
        f"{label}: simulation_revision not the last simulation-relevant commit",
    )
    check(
        doc["revisions"][-1]["committed_at"] == project["updated_at"],
        f"{label}: updated_at differs from last commit",
    )

    check(len(devices) <= 30, f"{label}: device cap exceeded")
    check(len(connections) <= 50, f"{label}: connection cap exceeded")

    names = [d["normalized_name"] for d in devices]
    check(len(names) == len(set(names)), f"{label}: duplicate normalized device name")
    for d in devices:
        check(d["normalized_name"] == norm(d["display_name"]), f"{label}: stale normalized_name")
        check(d["kind"] in DEVICE_KINDS, f"{label}: unknown device kind")
        gw = d.get("default_gateway_ipv4")
        if gw is not None:
            check(d["kind"] in {"PC", "SERVER"}, f"{label}: gateway on {d['kind']}")
            host_role_ok(gw, "gateway", label)

    seqs = sorted(d["device_sequence"] for d in devices)
    check(len(seqs) == len(set(seqs)) and all(x >= 1 for x in seqs),
          f"{label}: device_sequence not unique/positive")
    check(project["next_device_sequence"] > max(seqs, default=0),
          f"{label}: next_device_sequence does not exceed current allocations")

    per_device = {}
    for i in interfaces:
        per_device.setdefault(i["device_id"], []).append(i)
    for d in devices:
        owned = per_device.get(d["device_id"], [])
        expected = INVENTORY[d["kind"]]
        check(
            [i["display_name"] for i in owned] == expected,
            f"{label}: inventory mismatch on {d['display_name']}",
        )
        check(len({i["display_name"] for i in owned}) == len(owned), f"{label}: duplicate port name")
        check(sorted(i["ordinal"] for i in owned) == list(range(len(expected))), f"{label}: ordinals")
        if d["kind"] == "L2_SWITCH":
            check(all(i.get("ipv4") is None for i in owned), f"{label}: switch management IP")
        if d["kind"] in {"PC", "SERVER"}:
            check(len(owned) == 1, f"{label}: host interface count")
        for i in owned:
            check(i["interface_kind"] in SPEED, f"{label}: unknown interface kind")
            if i.get("ipv4"):
                check_interface_address(i["ipv4"], f"{label}/{d['display_name']}/{i['display_name']}")
        if d["kind"] == "ROUTER":
            check("next_route_sequence" in d, f"{label}: router missing route counter")

    macs = [i["mac_address"] for i in interfaces]
    check(len(macs) == len(set(macs)), f"{label}: duplicate MAC within project")
    check(
        len({i["mac_sequence"] for i in interfaces}) == len(interfaces),
        f"{label}: duplicate mac_sequence",
    )
    for i in interfaces:
        raw = i["mac_address"].replace(":", "")
        laa = int(raw[0:2], 16) & 0b10
        multicast = int(raw[0:2], 16) & 0b01
        check(laa == 2, f"{label}: MAC {i['mac_address']} not locally administered")
        check(multicast == 0, f"{label}: MAC {i['mac_address']} is multicast")
        check(
            i["mac_address"] == mac_for(project["project_id"], i["mac_sequence"]),
            f"{label}: MAC not reproducible from (project_id, mac_sequence)",
        )
        check(i["mac_sequence"] < project["next_mac_sequence"], f"{label}: mac_sequence >= counter")
    check(project["next_mac_sequence"] > max((i["mac_sequence"] for i in interfaces), default=0),
          f"{label}: next_mac_sequence does not exceed current allocations")

    by_iface = {i["interface_id"]: i for i in interfaces}
    used = set()
    for c in connections:
        a, b = c["interface_a_id"], c["interface_b_id"]
        check(a in by_iface and b in by_iface, f"{label}: dangling connection endpoint")
        check(a < b, f"{label}: endpoints not canonical")
        check(a != b, f"{label}: self-interface connection")
        for end in (a, b):
            check(end not in used, f"{label}: interface used by two connections")
            used.add(end)
        da = next(d for d in devices if d["device_id"] == by_iface[a]["device_id"])
        db = next(d for d in devices if d["device_id"] == by_iface[b]["device_id"])
        pair = tuple(sorted((MDI[da["kind"]], MDI[db["kind"]])))
        check(
            c["cable_type"] in CABLE_MATRIX[pair],
            f"{label}: cable {c['cable_type']} invalid for {pair}",
        )
    conn_seqs = [c["connection_sequence"] for c in connections]
    check(len(set(conn_seqs)) == len(conn_seqs) and all(x >= 1 for x in conn_seqs),
          f"{label}: connection_sequence not unique/positive")
    check(project["next_connection_sequence"] > max(conn_seqs, default=0),
          f"{label}: next_connection_sequence does not exceed current allocations")

    route_ids = {r["route_id"] for r in routes}
    check(len(route_ids) == len(routes), f"{label}: duplicate route_id")
    tuples = set()
    per_router = {}
    for r in routes:
        router = next((d for d in devices if d["device_id"] == r["router_device_id"]), None)
        check(router is not None and router["kind"] == "ROUTER", f"{label}: route on non-router")
        network = ipaddress.ip_network(
            f"{r['destination_network']}/{r['prefix_length']}", strict=True
        )
        check(
            str(network.network_address) == r["destination_network"],
            f"{label}: non-canonical destination network",
        )
        host_role_ok(r["next_hop_ipv4"], "next hop", label)
        key = (r["router_device_id"], r["destination_network"], r["prefix_length"], r["next_hop_ipv4"])
        check(key not in tuples, f"{label}: duplicate static route tuple")
        tuples.add(key)
        per_router.setdefault(r["router_device_id"], []).append(r)
    for dev_id, owned in per_router.items():
        seqs = [x["route_sequence"] for x in owned]
        # T4-DEC-09 / v1.0.1 8.4: per-router sequences are immutable and unique,
        # allocated monotonically; gaps left by a deletion are valid and are
        # never renumbered, so contiguity is NOT required.
        check(len(seqs) == len(set(seqs)), f"{label}: duplicate route_sequence on one router")
        check(all(s >= 1 for s in seqs), f"{label}: route_sequence below 1")
        dev = next(d for d in devices if d["device_id"] == dev_id)
        check(
            dev["next_route_sequence"] > max(seqs),
            f"{label}: next_route_sequence does not exceed every allocated sequence",
        )

    states, _ = interface_states(doc)
    # Persisted cabling is independent of runtime operational state. An
    # admin-disabled endpoint is a valid committed configuration (T1-CFG-02).
    for domain in l2_domains(doc):
        ips = [
            i["ipv4"]["address"]
            for i in interfaces
            if i.get("ipv4") and i["interface_id"] in domain
        ]
        # v1.0.1 6.4 / 8.4: TASK-02 accepts a duplicate address inside one L2
        # domain with a derived warning. It stays representable, so the model
        # validator must not reject it; it reports the warning instead.
        duplicated = sorted({ip for ip in ips if ips.count(ip) > 1})
        if duplicated:
            warn(f"{label}: DUPLICATE_IPV4_L2_DOMAIN accepted with warning on {duplicated}")
    return states


def summarize(doc, label, states):
    print(f"\n{label}  rev {doc['project']['state_revision']}")
    for d in doc["devices"]:
        ifaces = [i for i in doc["interfaces"] if i["device_id"] == d["device_id"]]
        live = [i for i in ifaces if states[i["interface_id"]][1]]
        print(
            f"  {d['display_name']:<8} {d['kind']:<10} ports {len(ifaces):>2}  operational {len(live):>2}"
            f"  gw {d.get('default_gateway_ipv4') or '-'}"
        )
    print(f"  connections {len(doc['connections'])}   static routes {len(doc['static_routes'])}")


def signature(doc):
    """Project-identity-independent structural fingerprint.

    MAC addresses are derived from the project id, so two fixtures with the same
    topology but different project ids legitimately carry different MACs.
    """
    devs = {d["device_id"]: d for d in doc["devices"]}
    dev_sig = sorted(
        (d["device_sequence"], d["kind"], d["display_name"], d.get("default_gateway_ipv4"))
        for d in doc["devices"]
    )
    iface_sig = sorted(
        (
            devs[i["device_id"]]["display_name"],
            i["display_name"],
            i["ordinal"],
            i["interface_kind"],
            i["admin_state"],
            (i["ipv4"]["address"], i["ipv4"]["prefix_length"]) if i.get("ipv4") else None,
        )
        for i in doc["interfaces"]
    )
    by_iface = {i["interface_id"]: i for i in doc["interfaces"]}
    conn_sig = sorted(
        (
            tuple(
                sorted(
                    (
                        devs[by_iface[c["interface_a_id"]]["device_id"]]["display_name"],
                        by_iface[c["interface_a_id"]]["display_name"],
                        devs[by_iface[c["interface_b_id"]]["device_id"]]["display_name"],
                        by_iface[c["interface_b_id"]]["display_name"],
                    )
                )
            ),
            c["cable_type"],
        )
        for c in doc["connections"]
    )
    route_sig = sorted(
        (
            devs[r["router_device_id"]]["display_name"],
            r["destination_network"],
            r["prefix_length"],
            r["next_hop_ipv4"],
            r["route_sequence"],
        )
        for r in doc["static_routes"]
    )
    return dev_sig, iface_sig, conn_sig, route_sig


def self_test(name, mutate):
    """Run the full rule set over a mutated RT-04 and require it to be accepted.

    v1.0.1 section 8.4 requires the checker to accept configurations TASK-02
    permits: a duplicate IPv4 inside one L2 domain and a route_sequence gap left
    by deletion. Each self-test counts as one assertion; the re-run of the shared
    rules is not double-counted.
    """
    global checks
    doc = json.loads(json.dumps(load(os.path.join(FIXTURES, "rt-04.json"))))
    mutate(doc)
    fail_mark, check_mark, warn_mark = len(failures), checks, len(warnings)
    validate_document(doc, f"self-test/{name}")
    produced = failures[fail_mark:]
    del failures[fail_mark:]
    emitted = warnings[warn_mark:]
    del warnings[warn_mark:]
    checks = check_mark
    check(not produced, f"self-test {name}: rejected a permitted state: {produced[:2]}")
    return emitted


def duplicate_ipv4(doc):
    """Give both ends of the R1-R2 transit link the same address."""
    transit = [
        i for i in doc["interfaces"] if i.get("ipv4") and i["ipv4"]["address"].startswith("10.0.12.")
    ]
    transit[1]["ipv4"] = dict(transit[0]["ipv4"])


def route_sequence_gap(doc):
    """Leave a gap as if lower-numbered routes had been deleted."""
    route = doc["static_routes"][0]
    route["route_sequence"] = 5
    router = next(d for d in doc["devices"] if d["device_id"] == route["router_device_id"])
    router["next_route_sequence"] = 6


def main():
    files = sorted(f for f in os.listdir(FIXTURES) if f.startswith("rt-") and f.endswith(".json"))
    docs = {}
    for name in files:
        doc = load(os.path.join(FIXTURES, name))
        label = name.replace(".json", "")
        docs[label] = doc
        states = validate_document(doc, label)
        summarize(doc, name, states)

    if "rt-04" in docs and "rt-05" in docs:
        rt4, rt5 = docs["rt-04"], docs["rt-05"]
        s4, s5 = signature(rt4), signature(rt5)
        labels = ("devices", "interfaces", "connections", "static routes")
        for label, a, b in zip(labels, s4, s5):
            if label == "static routes":
                continue
            check(a == b, f"rt-05 differs from rt-04 in {label}")
        r4, r5 = s4[3], s5[3]
        check(len(r4) == len(r5) + 1, "rt-05 does not have exactly one route fewer than rt-04")
        check(all(r in r4 for r in r5), "rt-05 routes are not a subset of rt-04 routes")

    # Accepted-with-warning states, proven rather than assumed (v1.0.1 8.4).
    emitted = self_test("duplicate-ipv4", duplicate_ipv4)
    check(
        any("DUPLICATE_IPV4_L2_DOMAIN" in w for w in emitted),
        "self-test duplicate-ipv4: accepted but emitted no derived warning",
    )
    self_test("route-sequence-gap", route_sequence_gap)

    print("\nself-tests (states the model must accept):")
    print("  duplicate IPv4 in one L2 domain     accepted, DUPLICATE_IPV4_L2_DOMAIN derived")
    print("  route_sequence gap after deletion   accepted, no renumbering required")

    print(f"\nchecks run: {checks}")
    if warnings:
        print("derived warnings on the fixtures:")
        for w in dict.fromkeys(warnings):
            print("  -", w)
    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS — schema + model invariants satisfied for:", ", ".join(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
