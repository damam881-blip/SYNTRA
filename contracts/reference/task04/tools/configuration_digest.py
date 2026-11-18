"""Compute the TASK-04 v1.0.0 configuration digest for a project document.

Section 7.4 of the design defines the canonical configuration projection:
presentation fields (position, rotation), wall-clock timestamps, project text,
checkpoints and the audit log are excluded; everything that can change network
behaviour is included. The digest therefore identifies a configuration, not a
scene or a moment in time.

Usage:  python tools/configuration_digest.py [fixtures/rt-04.json ...]
"""
import hashlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def projection(doc):
    devices = sorted(doc["devices"], key=lambda d: d["device_sequence"])
    order = {d["device_id"]: d["device_sequence"] for d in devices}
    interfaces = sorted(
        doc["interfaces"], key=lambda i: (order[i["device_id"]], i["ordinal"])
    )
    routes = sorted(
        doc["static_routes"], key=lambda r: (order[r["router_device_id"]], r["route_sequence"])
    )
    return {
        "schema_version": doc["schema_version"],
        "project": {"project_id": doc["project"]["project_id"]},
        "devices": [
            {
                "device_id": d["device_id"],
                "kind": d["kind"],
                "device_sequence": d["device_sequence"],
                "default_gateway_ipv4": d.get("default_gateway_ipv4"),
            }
            for d in devices
        ],
        "interfaces": [
            {
                "interface_id": i["interface_id"],
                "device_id": i["device_id"],
                "ordinal": i["ordinal"],
                "interface_kind": i["interface_kind"],
                "admin_state": i["admin_state"],
                "mac_address": i["mac_address"],
                "mac_sequence": i["mac_sequence"],
                "ipv4": i.get("ipv4"),
            }
            for i in interfaces
        ],
        "connections": [
            {
                "connection_id": c["connection_id"],
                "interface_a_id": c["interface_a_id"],
                "interface_b_id": c["interface_b_id"],
                "cable_type": c["cable_type"],
                "connection_sequence": c["connection_sequence"],
            }
            for c in sorted(doc["connections"], key=lambda c: c["connection_sequence"])
        ],
        "static_routes": [
            {
                "route_id": r["route_id"],
                "router_device_id": r["router_device_id"],
                "destination_network": r["destination_network"],
                "prefix_length": r["prefix_length"],
                "next_hop_ipv4": r["next_hop_ipv4"],
                "route_sequence": r["route_sequence"],
            }
            for r in routes
        ],
    }


def canonical_bytes(doc):
    payload = projection(doc)
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def digest(doc):
    return hashlib.sha256(canonical_bytes(doc)).hexdigest()


def verify():
    """Prove the projection is behavioural: presentation/metadata edits do not
    change it, configuration edits do."""
    with io.open(os.path.join(ROOT, "fixtures", "rt-04.json"), encoding="utf-8") as fh:
        base = json.load(fh)
    reference = digest(base)
    results = []

    moved = json.loads(json.dumps(base))
    moved["devices"][0]["position"] = {"x": 99.0, "y": 1.0, "z": -4.0}
    moved["devices"][0]["display_name"] = "Workstation-01"
    moved["devices"][0]["normalized_name"] = "workstation-01"
    moved["project"]["name"] = "Renamed project"
    moved["project"]["description"] = "metadata edit"
    results.append(("presentation + metadata edit keeps digest", digest(moved) == reference))

    reconfigured = json.loads(json.dumps(base))
    reconfigured["interfaces"][0]["ipv4"]["address"] = "192.168.10.99"
    results.append(("address edit changes digest", digest(reconfigured) != reference))

    disabled = json.loads(json.dumps(base))
    disabled["interfaces"][0]["admin_state"] = "DISABLED"
    results.append(("admin state edit changes digest", digest(disabled) != reference))

    reordered = json.loads(json.dumps(base))
    reordered["interfaces"] = list(reversed(reordered["interfaces"]))
    reordered["connections"] = list(reversed(reordered["connections"]))
    results.append(("input array order is irrelevant", digest(reordered) == reference))

    ok = True
    for label, passed in results:
        print(("PASS  " if passed else "FAIL  ") + label)
        ok = ok and passed
    print("\nreference digest:", reference)
    return 0 if ok else 1


def main(argv):
    if "--verify" in argv:
        return verify()
    paths = [a for a in argv[1:] if not a.startswith("--")]
    if not paths:
        fixture_dir = os.path.join(ROOT, "fixtures")
        paths = [
            os.path.join(fixture_dir, f)
            for f in sorted(os.listdir(fixture_dir))
            if f.endswith(".json")
        ]
    rows = []
    for path in paths:
        with io.open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        rows.append(
            {
                "fixture": os.path.basename(path),
                "state_revision": doc["project"]["state_revision"],
                "simulation_revision": doc["project"]["simulation_revision"],
                "configuration_digest": digest(doc),
            }
        )
        print(f"{os.path.basename(path):<12} rev {doc['project']['state_revision']:>2}  "
              f"sim {doc['project']['simulation_revision']:>2}  {digest(doc)}")
    if not argv[1:]:
        out = os.path.join(ROOT, "fixtures", "digests.json")
        with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rows, fh, indent=2)
            fh.write("\n")
        print("\nwrote", out)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
