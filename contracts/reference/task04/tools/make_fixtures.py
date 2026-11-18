"""Generate the TASK-04 reference-topology fixtures (RT-01..RT-05).

Deterministic: every identifier, MAC, sequence and timestamp is derived from the
fixture definition below, so re-running reproduces byte-identical documents.

Model rules exercised here (see TASK-04 section 6):
  * UUIDv7-shaped, opaque, stable entity ids
  * mac_address = 02 | sha256(project_id)[0:2] | uint24(mac_sequence)
  * immutable creation sequences (device, connection, route)
  * one append-only revision per committed mutation, gapless from 1
"""
import hashlib
import io
import json
import os
import unicodedata

BASE_TIME = "2026-10-24T09:00:00.000Z"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")

NS = "0190a4c2"
COUNTER = {"device": 0, "interface": 0, "connection": 0, "route": 0, "checkpoint": 0}


def uid(kind, n):
    prefix = {
        "project": "0001",
        "device": "0100",
        "interface": "0200",
        "connection": "0300",
        "route": "0400",
        "checkpoint": "0500",
    }[kind]
    return f"{NS}-{prefix}-7000-8000-{n:012x}"


def mac_for(project_id, seq):
    salt = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:4]
    raw = f"02{salt}{seq:06x}"
    return ":".join(raw[i:i + 2] for i in range(0, 12, 2))


def normalized(name):
    return unicodedata.normalize("NFC", name.strip()).casefold()


INVENTORY = {
    "PC": [("FastEthernet0", "FAST_ETHERNET")],
    "SERVER": [("FastEthernet0", "FAST_ETHERNET")],
    "L2_SWITCH": [
        ("FastEthernet0/1", "FAST_ETHERNET"),
        ("FastEthernet0/2", "FAST_ETHERNET"),
        ("FastEthernet0/3", "FAST_ETHERNET"),
        ("FastEthernet0/4", "FAST_ETHERNET"),
        ("FastEthernet0/5", "FAST_ETHERNET"),
        ("FastEthernet0/6", "FAST_ETHERNET"),
        ("GigabitEthernet0/1", "GIGABIT_ETHERNET"),
        ("GigabitEthernet0/2", "GIGABIT_ETHERNET"),
    ],
    "ROUTER": [
        ("FastEthernet0/0", "FAST_ETHERNET"),
        ("FastEthernet0/1", "FAST_ETHERNET"),
        ("GigabitEthernet0/0", "GIGABIT_ETHERNET"),
        ("GigabitEthernet0/1", "GIGABIT_ETHERNET"),
    ],
}


class Builder:
    def __init__(self, project_id, name, description):
        self.project_id = project_id
        self.doc = {
            "schema_version": "1.0.0",
            "project": {
                "project_id": project_id,
                "name": name,
                "description": description,
                "state_revision": 1,
                "simulation_revision": 1,
                "next_device_sequence": 1,
                "next_mac_sequence": 1,
                "next_connection_sequence": 1,
                "created_at": BASE_TIME,
                "updated_at": BASE_TIME,
            },
            "devices": [],
            "interfaces": [],
            "connections": [],
            "static_routes": [],
            "revisions": [
                {
                    "revision": 1,
                    "change_class": "TOPOLOGY",
                    "change_kinds": ["PROJECT_CREATED"],
                    "affected_entity_ids": [project_id],
                    "committed_at": BASE_TIME,
                }
            ],
        }
        self.clock = 0
        self.devices = {}

    # -- helpers ---------------------------------------------------------
    def tick(self):
        self.clock += 1
        s = self.clock
        return f"2026-10-24T09:{s // 60:02d}:{s % 60:02d}.000Z"

    def name_of(self, device_id):
        return self.devices[device_id]["display_name"]

    def commit(self, kinds, class_, affected):
        p = self.doc["project"]
        p["state_revision"] += 1
        if class_ in {"TOPOLOGY", "CONFIGURATION", "MIXED"}:
            p["simulation_revision"] = p["state_revision"]
        stamp = self.tick()
        p["updated_at"] = stamp
        self.doc["revisions"].append(
            {
                "revision": p["state_revision"],
                "change_class": class_,
                "change_kinds": kinds,
                "affected_entity_ids": affected,
                "committed_at": stamp,
            }
        )

    # -- operations ------------------------------------------------------
    def add_device(self, name, kind, ipv4=None, gateway=None, position=None):
        """ipv4: {"<port name>": (address, prefix_length)} or None."""
        COUNTER["device"] += 1
        n = COUNTER["device"]
        device_id = uid("device", n)
        kinds = ["DEVICE_ADDED"]
        affected = [device_id]
        device = {
            "device_id": device_id,
            "kind": kind,
            "display_name": name,
            "normalized_name": normalized(name),
            "device_sequence": n,
            "position": position or {"x": float(n * 3), "y": 0.0, "z": 0.0},
            "rotation_y_degrees": 0.0,
            "created_at": self.tick(),
        }
        if kind == "PC" or kind == "SERVER":
            device["default_gateway_ipv4"] = gateway
            if gateway is not None:
                kinds.append("HOST_GATEWAY_CONFIGURED")
        if kind == "ROUTER":
            device["next_route_sequence"] = 1
        self.devices[device_id] = device
        self.doc["devices"].append(device)
        p = self.doc["project"]
        p["next_device_sequence"] = n + 1

        for ordinal, (ifname, ikind) in enumerate(INVENTORY[kind]):
            COUNTER["interface"] += 1
            seq = self.doc["project"]["next_mac_sequence"]
            p["next_mac_sequence"] = seq + 1
            iface = {
                "interface_id": uid("interface", (n - 1) * 8 + ordinal + 1),
                "device_id": device_id,
                "display_name": ifname,
                "ordinal": ordinal,
                "interface_kind": ikind,
                "admin_state": "ENABLED",
                "mac_address": mac_for(self.project_id, seq),
                "mac_sequence": seq,
            }
            if ipv4 and ifname in ipv4:
                addr, prefix = ipv4[ifname]
                iface["ipv4"] = {"address": addr, "prefix_length": prefix}
                kinds.append("INTERFACE_IPV4_CONFIGURED")
            self.doc["interfaces"].append(iface)
        kinds = list(dict.fromkeys(kinds))
        self.commit(kinds, "MIXED" if len(kinds) > 2 else "TOPOLOGY", affected)
        return device_id

    def iface_id(self, device_name, port):
        dev = next(d for d in self.doc["devices"] if d["display_name"] == device_name)
        return next(
            i["interface_id"]
            for i in self.doc["interfaces"]
            if i["device_id"] == dev["device_id"] and i["display_name"] == port
        )

    def connect(self, dev_a, port_a, dev_b, port_b, cable="GENERIC_ETHERNET"):
        COUNTER["connection"] += 1
        n = COUNTER["connection"]
        a = self.iface_id(dev_a, port_a)
        b = self.iface_id(dev_b, port_b)
        if b < a:
            a, b = b, a
        conn = {
            "connection_id": uid("connection", n),
            "interface_a_id": a,
            "interface_b_id": b,
            "cable_type": cable,
            "connection_sequence": n,
            "created_at": self.tick(),
        }
        self.doc["connections"].append(conn)
        self.doc["project"]["next_connection_sequence"] = n + 1
        self.commit(["CONNECTION_ADDED"], "TOPOLOGY", [conn["connection_id"]])
        return conn["connection_id"]

    def route(self, router_name, network, prefix, next_hop):
        COUNTER["route"] += 1
        n = COUNTER["route"]
        dev = next(d for d in self.doc["devices"] if d["display_name"] == router_name)
        seq = dev["next_route_sequence"]
        dev["next_route_sequence"] = seq + 1
        r = {
            "route_id": uid("route", n),
            "router_device_id": dev["device_id"],
            "destination_network": network,
            "prefix_length": prefix,
            "next_hop_ipv4": next_hop,
            "route_sequence": seq,
            "created_at": self.tick(),
        }
        self.doc["static_routes"].append(r)
        self.commit(["STATIC_ROUTE_ADDED"], "CONFIGURATION", [r["route_id"]])
        return r["route_id"]

    def finish(self, path):
        doc = self.doc
        assert doc["project"]["state_revision"] == len(doc["revisions"])
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")


def reset():
    for k in COUNTER:
        COUNTER[k] = 0


def rt_01():
    reset()
    b = Builder(uid("project", 1), "RT-01 Basic LAN", "PC1-SW1-PC2 same subnet, no gateway")
    b.add_device("PC1", "PC", ipv4={"FastEthernet0": ("192.168.10.10", 24)})
    b.add_device("SW1", "L2_SWITCH")
    b.add_device("PC2", "PC", ipv4={"FastEthernet0": ("192.168.10.20", 24)})
    b.connect("PC1", "FastEthernet0", "SW1", "FastEthernet0/1")
    b.connect("PC2", "FastEthernet0", "SW1", "FastEthernet0/2")
    b.finish(os.path.join(OUT, "rt-01.json"))


def rt_02():
    reset()
    b = Builder(uid("project", 2), "RT-02 Server LAN", "PC1-SW1-Server1 same subnet, no gateway")
    b.add_device("PC1", "PC", ipv4={"FastEthernet0": ("192.168.10.10", 24)})
    b.add_device("SW1", "L2_SWITCH")
    b.add_device("Server1", "SERVER", ipv4={"FastEthernet0": ("192.168.10.100", 24)})
    b.connect("PC1", "FastEthernet0", "SW1", "FastEthernet0/1")
    b.connect("Server1", "FastEthernet0", "SW1", "FastEthernet0/2")
    b.finish(os.path.join(OUT, "rt-02.json"))


def rt_03():
    reset()
    b = Builder(uid("project", 3), "RT-03 One router", "PC1-R1-PC2 across two subnets")
    b.add_device("PC1", "PC", ipv4={"FastEthernet0": ("192.168.10.10", 24)}, gateway="192.168.10.1")
    b.add_device(
        "R1",
        "ROUTER",
        ipv4={"FastEthernet0/0": ("192.168.10.1", 24), "FastEthernet0/1": ("192.168.20.1", 24)},
    )
    b.add_device("PC2", "PC", ipv4={"FastEthernet0": ("192.168.20.10", 24)}, gateway="192.168.20.1")
    b.connect("PC1", "FastEthernet0", "R1", "FastEthernet0/0")
    b.connect("PC2", "FastEthernet0", "R1", "FastEthernet0/1")
    b.finish(os.path.join(OUT, "rt-03.json"))


def rt_04(drop_r2_return_route=False):
    reset()
    slug = "rt-05" if drop_r2_return_route else "rt-04"
    title = "RT-05 Missing return route" if drop_r2_return_route else "RT-04 Two routers"
    desc = (
        "RT-04 minus R2 static route to 192.168.10.0/24"
        if drop_r2_return_route
        else "PC1-R1-R2-PC2 with bidirectional static routes"
    )
    b = Builder(uid("project", 5 if drop_r2_return_route else 4), title, desc)
    b.add_device("PC1", "PC", ipv4={"FastEthernet0": ("192.168.10.10", 24)}, gateway="192.168.10.1")
    b.add_device(
        "R1",
        "ROUTER",
        ipv4={"FastEthernet0/0": ("192.168.10.1", 24), "FastEthernet0/1": ("10.0.12.1", 30)},
    )
    b.add_device(
        "R2",
        "ROUTER",
        ipv4={"FastEthernet0/0": ("10.0.12.2", 30), "FastEthernet0/1": ("192.168.20.1", 24)},
    )
    b.add_device("PC2", "PC", ipv4={"FastEthernet0": ("192.168.20.10", 24)}, gateway="192.168.20.1")
    b.connect("PC1", "FastEthernet0", "R1", "FastEthernet0/0")
    b.connect("R1", "FastEthernet0/1", "R2", "FastEthernet0/0")
    b.connect("R2", "FastEthernet0/1", "PC2", "FastEthernet0")
    b.route("R1", "192.168.20.0", 24, "10.0.12.2")
    if not drop_r2_return_route:
        b.route("R2", "192.168.10.0", 24, "10.0.12.1")
    b.finish(os.path.join(OUT, slug + ".json"))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    rt_01()
    rt_02()
    rt_03()
    rt_04()
    rt_04(drop_r2_return_route=True)
    print("written:", sorted(os.listdir(OUT)))
