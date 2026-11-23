"""Phase 3: deterministic, event-driven Ping simulation over a frozen topology.

``SimulatedPingRunner`` is the production implementation of the TASK-07 §8.2
``PingRunner`` port. It composes the approved TASK-03/04 primitives — virtual
event queue, host and router forwarding decisions, ARP resolution/cache,
Ethernet switch tables, IPv4 packets and ICMP echo correlation — then feeds the
observed evidence to the phase-2 result assembler.

It is pure ``dict -> dict``: no database, no API, no wall-clock time and no
topology mutation. Only identities, configuration and deterministic simulation
state influence the returned document.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID

from app.engine.arp.cache import ArpCache
from app.engine.arp.packet import (
    ArpMessage,
    ArpOperation,
    build_arp_request,
    request_frame_destination_mac,
)
from app.engine.arp.resolution import (
    ArpReplyEvidence,
    ArpResolutionContext,
    ArpResolutionStatus,
    arp_response_for,
)
from app.engine.clock.queue import (
    ARP_PROCESSING_NS,
    ARP_RESOLUTION_WINDOW_NS,
    BRANCH_TRAVERSAL_LIMIT,
    ENDPOINT_ICMP_PROCESSING_NS,
    LINK_PROPAGATION_NS,
    PING_DEADLINE_NS,
    REQUEST_EVENT_BUDGET,
    ROUTER_PROCESSING_NS,
    SWITCH_PROCESSING_NS,
    TEST_EVENT_BUDGET,
    BranchTraversalLimitExceeded,
    EventBudgetExhausted,
    EventQueue,
    transmission_delay_ns,
)
from app.engine.diagnostics.codes import (
    DiagnosticClassification,
    DiagnosticCode,
    EvidenceCompleteness,
)
from app.engine.ethernet.frame import EthernetFrame, FrameKind
from app.engine.ethernet.mac import BROADCAST_MAC, parse_mac
from app.engine.ethernet.switch_table import ForwardAction, SwitchMacTable
from app.engine.icmp.messages import (
    EchoMessage,
    EchoReplyCorrelator,
    ReplyMatchOutcome,
    RequestCorrelation,
    build_echo_request,
    icmp_error_allowed,
)
from app.engine.ipv4.address import parse_ipv4, prefix_mask
from app.engine.ipv4.packet import Ipv4Packet, build_ipv4_packet
from app.engine.ping.protocol import PingRunnerInput, PingRunnerResult
from app.engine.ping.result import (
    DEFAULT_ICMP_IDENTIFIER,
    REQUESTS_PLANNED,
    DiagnosticEvidence,
    EventEvidence,
    HopEvidence,
    RequestEvidence,
    ResultAssemblyError,
    ResultEvidence,
    assemble_result,
)
from app.engine.ping.topology import topology_from_replay_input
from app.engine.routing.decision import RouterForwardingTable, RouterInterface, StaticRouteConfig
from app.engine.routing.host import decide_host_forwarding
from app.engine.topology.models import (
    AdminState,
    Device,
    DeviceKind,
    Interface,
    InterfaceOperationalState,
    Project,
    derive_interface_states,
    is_uuid7,
)

# Evidence phase vocabulary (recorded in DEC-07-010).
_PHASE_CONTROL = 10
_PHASE_ROUTING = 20
_PHASE_ARP = 30
_PHASE_DATAPATH = 40
_PHASE_FAILURE = 50
_PHASE_OBSERVATION = 60
_PHASES = frozenset(
    {
        _PHASE_CONTROL,
        _PHASE_ROUTING,
        _PHASE_ARP,
        _PHASE_DATAPATH,
        _PHASE_FAILURE,
        _PHASE_OBSERVATION,
    }
)

# Frozen TASK-05 event vocabulary. Emitting anything outside this set is a bug.
_EVENT_KINDS = frozenset(
    {
        "FRAME_TX",
        "FRAME_ARRIVED",
        "FRAME_DROPPED",
        "DEVICE_PROCESSED",
        "ARP_REQUEST",
        "ARP_REPLY",
        "ARP_RESOLUTION",
        "ROUTE_SELECTED",
        "ROUTE_FAILED",
        "ICMP_ECHO_EMITTED",
        "ICMP_ECHO_MATCHED",
        "ICMP_ECHO_TIMEOUT",
        "ICMP_ERROR_GENERATED",
        "ICMP_ERROR_SUPPRESSED",
        "ICMP_ERROR_DELIVERED",
        "REQUEST_FINALIZED",
        "TEST_FINALIZED",
        "OBSERVATION_CLOSED",
        "PENDING_EVENTS_CANCELLED",
        "EXECUTION_LIMIT_REACHED",
        "LOCAL_ECHO_PROCESSED",
        "MAC_FLAPPING",
    }
)
_DIRECTIONS = frozenset({"FORWARD", "RETURN", "LOCAL", "DIAGNOSTIC", "NONE"})

_BITRATES = {"FAST_ETHERNET": 100_000_000, "GIGABIT_ETHERNET": 1_000_000_000}


@dataclass(frozen=True, slots=True)
class _StartRequest:
    sequence: int


@dataclass(frozen=True, slots=True)
class _RequestDeadline:
    sequence: int


@dataclass(frozen=True, slots=True)
class _FrameArrival:
    frame: EthernetFrame
    from_device_id: str
    from_interface_id: str
    to_device_id: str
    to_interface_id: str
    connection_id: str
    request_sequence: int
    direction: str
    arrived_at_ns: int
    frame_id: str
    packet_id: str | None


@dataclass(frozen=True, slots=True)
class _ArpDeadline:
    device_id: str
    target_ip: int
    request_sequence: int
    direction: str


@dataclass(frozen=True, slots=True)
class _Outbound:
    """An IPv4 packet waiting for next-hop MAC resolution."""

    packet: Ipv4Packet
    from_interface_id: str
    next_hop_ip: int
    request_sequence: int
    direction: str
    packet_id: str


@dataclass(frozen=True, slots=True)
class _RequestState:
    sequence: int
    started_at_ns: int
    emitted_at_ns: int | None = None
    finalized_at_ns: int | None = None
    outcome: str | None = None
    matched_reply_event_id: str | None = None
    primary_diagnostic_id: str | None = None
    forward_path_status: str = "NOT_STARTED"
    return_path_status: str = "NOT_STARTED"


@dataclass(slots=True)
class _Runtime:
    """Mutable per-run simulation state; never persisted and never shared."""

    project: Project
    queue: EventQueue[Any]
    destination_ip: int
    source_ip: int | None
    source_mask: int | None
    identifier: int
    source_device_id: str
    destination_device_id: str
    device_by_id: dict[str, Device] = field(default_factory=dict)
    interface_by_id: dict[str, Interface] = field(default_factory=dict)
    peer_by_interface: dict[str, tuple[str, str]] = field(default_factory=dict)
    switch_ports: dict[str, tuple[str, ...]] = field(default_factory=dict)
    operational: dict[str, bool] = field(default_factory=dict)
    local_ips: dict[str, frozenset[int]] = field(default_factory=dict)
    addresses: dict[int, tuple[str, str]] = field(default_factory=dict)
    mac_by_interface: dict[str, int] = field(default_factory=dict)
    switch_tables: dict[str, SwitchMacTable] = field(default_factory=dict)
    arp_caches: dict[str, ArpCache] = field(default_factory=dict)
    router_tables: dict[str, RouterForwardingTable] = field(default_factory=dict)
    correlator: EchoReplyCorrelator = field(default_factory=EchoReplyCorrelator)
    requests: dict[int, _RequestState] = field(default_factory=dict)
    events: list[EventEvidence] = field(default_factory=list)
    diagnostics: list[DiagnosticEvidence] = field(default_factory=list)
    hops: list[HopEvidence] = field(default_factory=list)
    arp_contexts: dict[tuple[str, int], ArpResolutionContext] = field(default_factory=dict)
    pending: dict[tuple[str, int], list[_Outbound]] = field(default_factory=dict)
    frame_index: int = 0
    packet_index: int = 0
    diagnostic_index: int = 0
    hop_index: int = 0
    execution_limit_code: DiagnosticCode | None = None


class SimulatedPingRunner:
    """Run four real echo requests on a frozen snapshot, then assemble a result."""

    def __init__(
        self,
        *,
        icmp_identifier: int = DEFAULT_ICMP_IDENTIFIER,
        request_event_budget: int | None = REQUEST_EVENT_BUDGET,
        test_event_budget: int | None = TEST_EVENT_BUDGET,
        branch_traversal_limit: int = BRANCH_TRAVERSAL_LIMIT,
        arp_window_ns: int = ARP_RESOLUTION_WINDOW_NS,
    ) -> None:
        if not 0 <= icmp_identifier <= 0xFFFF:
            raise ValueError("icmp_identifier must be a 16-bit integer")
        if arp_window_ns < 0:
            raise ValueError("arp_window_ns must be non-negative")
        self._icmp_identifier = icmp_identifier
        self._request_event_budget = request_event_budget
        self._test_event_budget = test_event_budget
        self._branch_traversal_limit = branch_traversal_limit
        self._arp_window_ns = arp_window_ns

    def run(
        self,
        replay_input: PingRunnerInput,
        *,
        test_id: UUID,
        project_id: UUID,
        source_device_id: UUID,
        destination_device_id: UUID,
    ) -> PingRunnerResult:
        """Return one complete TASK-05 result produced by deterministic simulation."""
        project = topology_from_replay_input(replay_input)
        if project.project_id != str(project_id):
            raise ResultAssemblyError("snapshot project does not match the command")
        evidence = self._simulate(
            project,
            test_id=str(test_id),
            project_id=str(project_id),
            source_device_id=str(source_device_id),
            destination_device_id=str(destination_device_id),
            snapshot_ref=self._snapshot_ref(replay_input, str(project_id)),
        )
        return assemble_result(evidence)

    @staticmethod
    def _snapshot_ref(replay_input: PingRunnerInput, project_id: str) -> dict[str, object]:
        return {
            "project_id": project_id,
            "snapshot_id": replay_input["snapshot_id"],
            "base_state_revision": replay_input["base_state_revision"],
            "base_simulation_revision": replay_input["base_simulation_revision"],
            "schema_version": replay_input["schema_version"],
            "configuration_digest": replay_input["configuration_digest"],
        }

    # --- topology views -------------------------------------------------------

    def _build_runtime(
        self,
        project: Project,
        *,
        test_id: str,
        project_id: str,
        source_device_id: str,
        destination_device_id: str,
        snapshot_ref: dict[str, object],
    ) -> _Runtime:
        del test_id  # The logical UUID test id is not used as an ICMP identifier.
        device_by_id = {device.device_id: device for device in project.devices}
        interface_by_id = {interface.interface_id: interface for interface in project.interfaces}
        if source_device_id not in device_by_id or destination_device_id not in device_by_id:
            raise ResultAssemblyError("ping endpoints must belong to the frozen topology")
        if str(snapshot_ref["project_id"]) != project_id:
            raise ResultAssemblyError("snapshot project does not match the command")

        peer_by_interface: dict[str, tuple[str, str]] = {}
        for connection in project.connections:
            peer_by_interface[connection.interface_a_id] = (
                connection.interface_b_id,
                connection.connection_id,
            )
            peer_by_interface[connection.interface_b_id] = (
                connection.interface_a_id,
                connection.connection_id,
            )

        states = {state.interface_id: state for state in derive_interface_states(project)}
        operational = {
            interface_id: state.operational_state is InterfaceOperationalState.OPERATIONAL
            for interface_id, state in states.items()
        }
        switch_ports: dict[str, tuple[str, ...]] = {}
        for device in project.devices:
            if device.kind is not DeviceKind.L2_SWITCH:
                continue
            switch_ports[device.device_id] = tuple(
                interface.interface_id
                for interface in project.interfaces
                if interface.device_id == device.device_id
            )

        mac_by_interface = {
            interface.interface_id: parse_mac(interface.mac_address)
            for interface in project.interfaces
        }
        local_ips: dict[str, frozenset[int]] = {
            device_id: frozenset() for device_id in device_by_id
        }
        addresses: dict[int, tuple[str, str]] = {}
        for interface in project.interfaces:
            if interface.ipv4 is None:
                continue
            address = parse_ipv4(interface.ipv4.address)
            addresses[address] = (interface.interface_id, interface.device_id)
            local_ips[interface.device_id] = local_ips[interface.device_id] | {address}

        switch_tables = {device_id: SwitchMacTable() for device_id in switch_ports}
        arp_caches = {
            device.device_id: ArpCache()
            for device in project.devices
            if device.kind in (DeviceKind.PC, DeviceKind.SERVER, DeviceKind.ROUTER)
        }
        router_tables: dict[str, RouterForwardingTable] = {}
        for device in project.devices:
            if device.kind is not DeviceKind.ROUTER:
                continue
            router_interfaces = [
                RouterInterface(
                    interface_id=interface.interface_id,
                    device_id=device.device_id,
                    ordinal=interface.ordinal,
                    device_sequence=device.device_sequence,
                    address=parse_ipv4(interface.ipv4.address)
                    if interface.ipv4 is not None
                    else None,
                    prefix_length=interface.ipv4.prefix_length
                    if interface.ipv4 is not None
                    else None,
                    admin_enabled=interface.admin_state is AdminState.ENABLED,
                    link_operational=operational[interface.interface_id],
                )
                for interface in project.interfaces
                if interface.device_id == device.device_id
            ]
            routes = tuple(
                StaticRouteConfig.from_topology_route(route)
                for route in project.static_routes
                if route.router_device_id == device.device_id
            )
            router_tables[device.device_id] = RouterForwardingTable(router_interfaces, routes)

        queue: EventQueue[Any] = EventQueue(
            request_event_budget=self._request_event_budget,
            test_event_budget=self._test_event_budget,
            branch_traversal_limit=self._branch_traversal_limit,
        )
        source_interface = next(
            (
                interface
                for interface in project.interfaces
                if interface.device_id == source_device_id and interface.ipv4
            ),
            None,
        )
        destination_interface = next(
            (
                interface
                for interface in project.interfaces
                if interface.device_id == destination_device_id and interface.ipv4
            ),
            None,
        )
        if destination_interface is None or destination_interface.ipv4 is None:
            raise ResultAssemblyError("destination device has no configured IPv4 address")
        source_ip = (
            parse_ipv4(source_interface.ipv4.address)
            if source_interface is not None and source_interface.ipv4 is not None
            else None
        )
        source_mask = (
            prefix_mask(source_interface.ipv4.prefix_length)
            if source_interface is not None and source_interface.ipv4 is not None
            else None
        )

        return _Runtime(
            project=project,
            queue=queue,
            destination_ip=parse_ipv4(destination_interface.ipv4.address),
            source_ip=source_ip,
            source_mask=source_mask,
            identifier=self._icmp_identifier,
            source_device_id=source_device_id,
            destination_device_id=destination_device_id,
            device_by_id=device_by_id,
            interface_by_id=interface_by_id,
            peer_by_interface=peer_by_interface,
            switch_ports=switch_ports,
            operational=operational,
            local_ips=local_ips,
            addresses=addresses,
            mac_by_interface=mac_by_interface,
            switch_tables=switch_tables,
            arp_caches=arp_caches,
            router_tables=router_tables,
        )

    # --- evidence emission ----------------------------------------------------

    @staticmethod
    def _emit(
        runtime: _Runtime,
        *,
        time_ns: int,
        kind: str,
        direction: str,
        request_sequence: int | None = None,
        phase: int = _PHASE_DATAPATH,
        device_id: str | None = None,
        ingress_interface_id: str | None = None,
        egress_interface_id: str | None = None,
        connection_id: str | None = None,
        packet_id: str | None = None,
        frame_id: str | None = None,
        resolution_id: str | None = None,
        diagnostic_id: str | None = None,
        facts: dict[str, object] | None = None,
    ) -> EventEvidence:
        if kind not in _EVENT_KINDS or direction not in _DIRECTIONS or phase not in _PHASES:
            raise ResultAssemblyError(f"invalid evidence vocabulary: {kind}/{direction}/{phase}")
        if runtime.events and time_ns < runtime.events[-1].virtual_time_ns:
            raise ResultAssemblyError("evidence events are not time-ordered")
        index = len(runtime.events) + 1
        event = EventEvidence(
            event_id=f"ev-{index:05d}",
            virtual_time_ns=time_ns,
            phase=phase,
            kind=kind,
            direction=direction,
            execution_index=index,
            creation_sequence=index,
            request_sequence=request_sequence,
            device_id=device_id,
            ingress_interface_id=ingress_interface_id,
            egress_interface_id=egress_interface_id,
            connection_id=connection_id,
            packet_id=packet_id,
            frame_id=frame_id,
            resolution_id=resolution_id,
            diagnostic_id=diagnostic_id,
            facts=facts or {},
        )
        runtime.events.append(event)
        return event

    def _diagnose(
        self,
        runtime: _Runtime,
        *,
        code: DiagnosticCode,
        request_sequence: int,
        direction: str,
        time_ns: int,
        device_id: str | None = None,
        interface_id: str | None = None,
        classification: DiagnosticClassification = DiagnosticClassification.SIMULATION_FAILURE,
        completeness: EvidenceCompleteness = EvidenceCompleteness.COMPLETE,
        facts: dict[str, object] | None = None,
    ) -> str:
        runtime.diagnostic_index += 1
        diagnostic_id = f"diag-{runtime.diagnostic_index:05d}"
        runtime.diagnostics.append(
            DiagnosticEvidence(
                diagnostic_id=diagnostic_id,
                code=code.value,
                classification=classification.value,
                is_primary=True,
                request_sequence=request_sequence,
                direction=direction,
                detected_at_ns=time_ns,
                detected_device_id=device_id,
                detected_interface_id=interface_id,
                trigger_event_id=None,
                evidence_completeness=completeness.value,
                facts=facts or {},
            )
        )
        return diagnostic_id

    # --- L2 forwarding --------------------------------------------------------

    @staticmethod
    def _next_frame_id(runtime: _Runtime) -> str:
        runtime.frame_index += 1
        return f"frame-{runtime.frame_index:05d}"

    @staticmethod
    def _next_packet_id(runtime: _Runtime) -> str:
        runtime.packet_index += 1
        return f"pkt-{runtime.packet_index:05d}"

    @staticmethod
    def _bitrate(interface: Interface) -> int:
        return _BITRATES[interface.interface_kind.value]

    @staticmethod
    def _arp_code(status: ArpResolutionStatus | None) -> DiagnosticCode:
        if status is ArpResolutionStatus.SAFETY_LIMITED:
            return DiagnosticCode.ARP_SAFETY_LIMITED
        if status is ArpResolutionStatus.AMBIGUOUS:
            return DiagnosticCode.ARP_AMBIGUOUS_RESPONSE
        return DiagnosticCode.ARP_NO_RESPONSE

    @staticmethod
    def _packet_type(frame: EthernetFrame) -> str | None:
        """Derive the fact value lazily; ARP and error payloads are not IP packets."""
        payload = frame.payload
        if isinstance(payload, ArpMessage):
            return "ARP_REQUEST" if payload.is_request else "ARP_REPLY"
        if isinstance(payload, Ipv4Packet):
            inner = payload.payload
            if isinstance(inner, EchoMessage):
                return "ECHO_REPLY" if inner.is_reply else "ECHO_REQUEST"
            if getattr(inner, "is_icmp_error", False):
                return "ICMP_ERROR"
        return None

    def _send_frame(
        self,
        runtime: _Runtime,
        *,
        from_interface_id: str,
        destination_mac: int,
        frame: EthernetFrame,
        request_sequence: int,
        direction: str,
        time_ns: int,
        packet_id: str | None,
        frame_id: str | None = None,
    ) -> None:
        self._transmit_from_interface(
            runtime,
            from_interface_id=from_interface_id,
            destination_mac=destination_mac,
            frame=frame,
            request_sequence=request_sequence,
            direction=direction,
            time_ns=time_ns,
            packet_id=packet_id,
            frame_id=frame_id or self._next_frame_id(runtime),
        )

    def _transmit_from_interface(
        self,
        runtime: _Runtime,
        *,
        from_interface_id: str,
        destination_mac: int,
        frame: EthernetFrame,
        request_sequence: int,
        direction: str,
        time_ns: int,
        packet_id: str | None,
        frame_id: str,
    ) -> None:
        peer = runtime.peer_by_interface.get(from_interface_id)
        if peer is None:
            return
        peer_interface_id, connection_id = peer
        sender = runtime.interface_by_id[from_interface_id]
        delay = transmission_delay_ns(frame.total_bytes, self._bitrate(sender))
        arrival_time = time_ns + delay + LINK_PROPAGATION_NS
        self._emit(
            runtime,
            time_ns=time_ns,
            kind="FRAME_TX",
            direction=direction,
            request_sequence=request_sequence,
            device_id=sender.device_id,
            egress_interface_id=from_interface_id,
            connection_id=connection_id,
            packet_id=packet_id,
            frame_id=frame_id,
            facts={"packet_type": self._packet_type(frame)},
        )
        runtime.queue.schedule(
            arrival_time,
            _PHASE_DATAPATH,
            _FrameArrival(
                frame=frame,
                from_device_id=sender.device_id,
                from_interface_id=from_interface_id,
                to_device_id=runtime.interface_by_id[peer_interface_id].device_id,
                to_interface_id=peer_interface_id,
                connection_id=connection_id,
                request_sequence=request_sequence,
                direction=direction,
                arrived_at_ns=arrival_time,
                frame_id=frame_id,
                packet_id=packet_id,
            ),
            branch_id=f"req-{request_sequence}",
        )

    def _handle_frame_arrival(self, runtime: _Runtime, arrival: _FrameArrival) -> None:
        self._emit(
            runtime,
            time_ns=arrival.arrived_at_ns,
            kind="FRAME_ARRIVED",
            direction=arrival.direction,
            request_sequence=arrival.request_sequence,
            device_id=arrival.to_device_id,
            ingress_interface_id=arrival.to_interface_id,
            connection_id=arrival.connection_id,
            packet_id=arrival.packet_id,
            frame_id=arrival.frame_id,
            facts={"packet_type": self._packet_type(arrival.frame)},
        )
        device = runtime.device_by_id[arrival.to_device_id]
        if device.kind is DeviceKind.L2_SWITCH:
            self._switch_forward(runtime, arrival)
            return
        if not self._mac_addressed_here(runtime, arrival.to_device_id, arrival.frame):
            return
        if isinstance(arrival.frame.payload, ArpMessage):
            self._handle_arp_message(runtime, arrival, arrival.frame.payload)
        elif isinstance(arrival.frame.payload, Ipv4Packet):
            self._handle_ipv4(runtime, arrival, arrival.frame.payload)

    def _mac_addressed_here(self, runtime: _Runtime, device_id: str, frame: EthernetFrame) -> bool:
        if frame.destination_mac == BROADCAST_MAC:
            return True
        return any(
            interface.device_id == device_id
            and runtime.mac_by_interface[interface.interface_id] == frame.destination_mac
            for interface in runtime.interface_by_id.values()
        )

    def _switch_forward(self, runtime: _Runtime, arrival: _FrameArrival) -> None:
        switch_id = arrival.to_device_id
        table = runtime.switch_tables[switch_id]
        eligible = [
            port
            for port in runtime.switch_ports[switch_id]
            if port != arrival.to_interface_id
            and port in runtime.peer_by_interface
            and runtime.operational.get(port, False)
        ]
        _, decision = table.decide(
            ingress_port=arrival.to_interface_id,
            source_mac=arrival.frame.source_mac,
            destination_mac=arrival.frame.destination_mac,
            eligible_ports=eligible,
            now_ns=arrival.arrived_at_ns,
        )
        if decision.action is ForwardAction.FILTER:
            return
        for port in decision.egress_ports:
            self._transmit_from_interface(
                runtime,
                from_interface_id=port,
                destination_mac=arrival.frame.destination_mac,
                frame=arrival.frame,
                request_sequence=arrival.request_sequence,
                direction=arrival.direction,
                time_ns=arrival.arrived_at_ns + SWITCH_PROCESSING_NS,
                packet_id=arrival.packet_id,
                frame_id=arrival.frame_id,
            )

    # --- ARP ------------------------------------------------------------------

    def _arp_request_frame(self, sender_mac: int, sender_ip: int, target_ip: int) -> EthernetFrame:
        message = build_arp_request(sender_mac, sender_ip, target_ip)
        return EthernetFrame(
            destination_mac=request_frame_destination_mac(message),
            source_mac=sender_mac,
            kind=FrameKind.ARP,
            payload=message,
        )

    def _handle_arp_message(
        self, runtime: _Runtime, arrival: _FrameArrival, message: ArpMessage
    ) -> None:
        now = arrival.arrived_at_ns
        interface = runtime.interface_by_id[arrival.to_interface_id]
        local_ip = parse_ipv4(interface.ipv4.address) if interface.ipv4 is not None else None
        if message.operation is ArpOperation.REQUEST:
            self._emit(
                runtime,
                time_ns=now,
                kind="ARP_REQUEST",
                direction=arrival.direction,
                request_sequence=arrival.request_sequence,
                phase=_PHASE_ARP,
                device_id=arrival.to_device_id,
                ingress_interface_id=arrival.to_interface_id,
                facts={"target_ipv4": message.target_ip, "packet_type": "ARP_REQUEST"},
            )
            reply = arp_response_for(
                runtime.device_by_id[arrival.to_device_id].kind,
                message,
                local_ip,
                runtime.mac_by_interface[arrival.to_interface_id],
            )
            if reply is not None:
                frame = EthernetFrame(
                    destination_mac=reply.target_mac,
                    source_mac=reply.sender_mac,
                    kind=FrameKind.ARP,
                    payload=reply,
                )
                self._send_frame(
                    runtime,
                    from_interface_id=arrival.to_interface_id,
                    destination_mac=reply.target_mac,
                    frame=frame,
                    request_sequence=arrival.request_sequence,
                    direction="RETURN",
                    time_ns=now + ARP_PROCESSING_NS,
                    packet_id=None,
                )
            return

        self._emit(
            runtime,
            time_ns=now,
            kind="ARP_REPLY",
            direction="RETURN",
            request_sequence=arrival.request_sequence,
            phase=_PHASE_ARP,
            device_id=arrival.to_device_id,
            ingress_interface_id=arrival.to_interface_id,
            facts={"target_ipv4": message.sender_ip, "packet_type": "ARP_REPLY"},
        )
        responder_entry = runtime.addresses.get(message.sender_ip)
        responding_device_id = (
            responder_entry[1] if responder_entry is not None else arrival.from_device_id
        )
        key = (arrival.to_device_id, message.sender_ip)
        context = runtime.arp_contexts.get(key)
        if context is None or context.is_finalized:
            return
        outcome = context.observe(
            ArpReplyEvidence(
                responding_device_id=responding_device_id,
                ip=message.sender_ip,
                mac=message.sender_mac,
                arrived_at_ns=now,
                context_id=context.context_id,
            )
        )
        if outcome.value != "ACCEPTED":
            return
        result = context.finalize(now, all_branches_complete=True)
        self._emit(
            runtime,
            time_ns=now,
            kind="ARP_RESOLUTION",
            direction="DIAGNOSTIC",
            request_sequence=arrival.request_sequence,
            phase=_PHASE_ARP,
            device_id=arrival.to_device_id,
            resolution_id=context.context_id,
            facts={
                "target_ipv4": message.sender_ip,
                "observed_responder_count": len(result.responders),
            },
        )
        context.apply_to_cache(runtime.arp_caches[arrival.to_device_id])
        self._release_pending(runtime, key, now)

    def _resolve_and_send(
        self,
        runtime: _Runtime,
        *,
        device_id: str,
        from_interface_id: str,
        next_hop_ip: int,
        outbound: _Outbound,
        time_ns: int,
    ) -> None:
        cache = runtime.arp_caches.get(device_id)
        mac = None if cache is None else cache.lookup(next_hop_ip, time_ns)
        if mac is not None:
            self._send_ipv4(runtime, outbound=outbound, destination_mac=mac, time_ns=time_ns)
            return

        key = (device_id, next_hop_ip)
        context = runtime.arp_contexts.get(key)
        if context is not None and context.is_finalized:
            result = context.result
            self._fail_request(
                runtime,
                outbound.request_sequence,
                outcome="FAILED",
                code=self._arp_code(None if result is None else result.status),
                direction=outbound.direction,
                time_ns=time_ns,
                device_id=device_id,
            )
            return
        if context is None:
            context = ArpResolutionContext(
                next_hop_ip,
                time_ns,
                window_ns=self._arp_window_ns,
                context_id=f"arp-{device_id[-4:]}-{len(runtime.arp_contexts) + 1:03d}",
            )
            runtime.arp_contexts[key] = context
            sender_mac = runtime.mac_by_interface[from_interface_id]
            frame = self._arp_request_frame(sender_mac, outbound.packet.source, next_hop_ip)
            self._emit(
                runtime,
                time_ns=time_ns,
                kind="ARP_REQUEST",
                direction="FORWARD" if outbound.direction == "FORWARD" else "RETURN",
                request_sequence=outbound.request_sequence,
                phase=_PHASE_ARP,
                device_id=device_id,
                egress_interface_id=from_interface_id,
                facts={"target_ipv4": next_hop_ip, "packet_type": "ARP_REQUEST"},
            )
            runtime.queue.schedule(
                context.deadline_ns,
                _PHASE_FAILURE,
                _ArpDeadline(
                    device_id=device_id,
                    target_ip=next_hop_ip,
                    request_sequence=outbound.request_sequence,
                    direction=outbound.direction,
                ),
                branch_id=f"req-{outbound.request_sequence}",
            )
            self._send_frame(
                runtime,
                from_interface_id=from_interface_id,
                destination_mac=request_frame_destination_mac(frame.payload),
                frame=frame,
                request_sequence=outbound.request_sequence,
                direction=outbound.direction,
                time_ns=time_ns,
                packet_id=None,
            )
        runtime.pending.setdefault(key, []).append(outbound)

    def _release_pending(self, runtime: _Runtime, key: tuple[str, int], now: int) -> None:
        pending = runtime.pending.pop(key, [])
        context = runtime.arp_contexts.get(key)
        cache = runtime.arp_caches.get(key[0])
        if context is None or cache is None:
            return
        context.apply_to_cache(cache)
        mac = cache.lookup(key[1], now)
        if mac is None:
            return
        for outbound in pending:
            self._send_ipv4(runtime, outbound=outbound, destination_mac=mac, time_ns=now)

    def _handle_arp_deadline(self, runtime: _Runtime, deadline: _ArpDeadline) -> None:
        key = (deadline.device_id, deadline.target_ip)
        context = runtime.arp_contexts.get(key)
        if context is None or context.is_finalized:
            return
        now = runtime.queue.now_ns
        result = context.finalize(now, all_branches_complete=True)
        classification = (
            DiagnosticClassification.EXECUTION_LIMIT
            if result.status is ArpResolutionStatus.SAFETY_LIMITED
            else DiagnosticClassification.SIMULATION_FAILURE
        )
        self._emit(
            runtime,
            time_ns=now,
            kind="ARP_RESOLUTION",
            direction="DIAGNOSTIC",
            request_sequence=deadline.request_sequence,
            phase=_PHASE_FAILURE,
            device_id=deadline.device_id,
            resolution_id=context.context_id,
            facts={
                "target_ipv4": deadline.target_ip,
                "observed_responder_count": len(result.responders),
            },
        )
        pending = runtime.pending.pop(key, [])
        sequences = sorted({outbound.request_sequence for outbound in pending})
        if not sequences:
            sequences = [deadline.request_sequence]
        for sequence in sequences:
            self._fail_request(
                runtime,
                sequence,
                outcome="FAILED",
                code=self._arp_code(result.status),
                direction=deadline.direction,
                time_ns=now,
                device_id=deadline.device_id,
                classification=classification,
            )

    # --- IPv4 / ICMP ----------------------------------------------------------

    def _send_ipv4(
        self, runtime: _Runtime, *, outbound: _Outbound, destination_mac: int, time_ns: int
    ) -> None:
        payload = outbound.packet.payload
        kind = (
            FrameKind.ICMP_TIME_EXCEEDED
            if getattr(payload, "is_icmp_error", False)
            else FrameKind.ICMP_ECHO
        )
        frame = EthernetFrame(
            destination_mac=destination_mac,
            source_mac=runtime.mac_by_interface[outbound.from_interface_id],
            kind=kind,
            payload=outbound.packet,
        )
        self._send_frame(
            runtime,
            from_interface_id=outbound.from_interface_id,
            destination_mac=destination_mac,
            frame=frame,
            request_sequence=outbound.request_sequence,
            direction=outbound.direction,
            time_ns=time_ns,
            packet_id=outbound.packet_id,
        )

    def _handle_ipv4(self, runtime: _Runtime, arrival: _FrameArrival, packet: Ipv4Packet) -> None:
        now = arrival.arrived_at_ns
        sequence = arrival.request_sequence
        device = runtime.device_by_id[arrival.to_device_id]
        if packet.destination in runtime.local_ips[device.device_id]:
            self._deliver_icmp(runtime, arrival, packet, now)
            return
        if device.kind is not DeviceKind.ROUTER:
            self._fail_request(
                runtime,
                sequence,
                outcome="FAILED",
                code=DiagnosticCode.ECHO_REQUEST_DROPPED
                if arrival.direction == "FORWARD"
                else DiagnosticCode.ECHO_REPLY_DROPPED,
                direction=arrival.direction,
                time_ns=now,
                device_id=device.device_id,
                interface_id=arrival.to_interface_id,
            )
            return
        decision = runtime.router_tables[device.device_id].decide(
            packet.destination,
            ttl=packet.ttl,
            ingress_interface_id=arrival.to_interface_id,
        )
        if decision.is_local:
            self._deliver_icmp(runtime, arrival, packet, now)
            return
        if not decision.is_forwarded:
            reason = (
                decision.ineligible_candidates[0].ineligible_reason
                if decision.ineligible_candidates
                and decision.ineligible_candidates[0].ineligible_reason is not None
                else decision.diagnostic_code
            )
            self._emit(
                runtime,
                time_ns=now,
                kind="ROUTE_FAILED",
                direction=arrival.direction,
                request_sequence=sequence,
                phase=_PHASE_ROUTING,
                device_id=device.device_id,
                ingress_interface_id=arrival.to_interface_id,
                facts={
                    "target_ipv4": packet.destination,
                    "ttl_before": packet.ttl,
                    "router_id": device.device_id,
                },
            )
            self._fail_request(
                runtime,
                sequence,
                outcome="FAILED",
                code=reason or DiagnosticCode.NO_MATCHING_ROUTE,
                direction=arrival.direction,
                time_ns=now,
                device_id=device.device_id,
                interface_id=arrival.to_interface_id,
            )
            return
        egress = decision.egress_interface_id
        if egress is None:
            self._fail_request(
                runtime,
                sequence,
                outcome="FAILED",
                code=DiagnosticCode.NO_ELIGIBLE_ROUTE,
                direction=arrival.direction,
                time_ns=now,
                device_id=device.device_id,
            )
            return
        route_id = decision.selected.source_id if decision.selected is not None else None
        self._emit(
            runtime,
            time_ns=now,
            kind="ROUTE_SELECTED",
            direction=arrival.direction,
            request_sequence=sequence,
            phase=_PHASE_ROUTING,
            device_id=device.device_id,
            ingress_interface_id=arrival.to_interface_id,
            egress_interface_id=egress,
            facts={
                "target_ipv4": packet.destination,
                "ttl_before": packet.ttl,
                "ttl_after": packet.ttl - 1,
                "route_id": route_id if is_uuid7(str(route_id)) else None,
                "router_id": device.device_id,
            },
        )
        outbound = _Outbound(
            packet=packet.forwarded(),
            from_interface_id=egress,
            next_hop_ip=decision.next_hop or packet.destination,
            request_sequence=sequence,
            direction=arrival.direction,
            packet_id=self._next_packet_id(runtime),
        )
        self._resolve_and_send(
            runtime,
            device_id=device.device_id,
            from_interface_id=egress,
            next_hop_ip=outbound.next_hop_ip,
            outbound=outbound,
            time_ns=now + ROUTER_PROCESSING_NS,
        )

    def _deliver_icmp(
        self, runtime: _Runtime, arrival: _FrameArrival, packet: Ipv4Packet, now: int
    ) -> None:
        message = packet.payload
        if not isinstance(message, EchoMessage):
            return
        sequence = arrival.request_sequence
        if message.is_request:
            reply = message.as_reply()
            if not icmp_error_allowed(reply.destination, reply):
                self._emit(
                    runtime,
                    time_ns=now,
                    kind="ICMP_ERROR_SUPPRESSED",
                    direction="RETURN",
                    request_sequence=sequence,
                    phase=_PHASE_FAILURE,
                    device_id=arrival.to_device_id,
                    facts={"target_ipv4": reply.destination},
                )
                return
            interface = runtime.interface_by_id[arrival.to_interface_id]
            if interface.ipv4 is None:
                self._fail_request(
                    runtime,
                    sequence,
                    outcome="FAILED",
                    code=DiagnosticCode.SOURCE_IPV4_UNCONFIGURED,
                    direction="RETURN",
                    time_ns=now,
                    device_id=arrival.to_device_id,
                    forward_status="COMPLETED",
                    return_status="FAILED",
                )
                return
            decision = decide_host_forwarding(
                reply.destination,
                source_address=parse_ipv4(interface.ipv4.address),
                mask=prefix_mask(interface.ipv4.prefix_length),
                gateway=self._gateway_of(runtime, arrival.to_device_id),
            )
            if not decision.is_usable:
                self._emit(
                    runtime,
                    time_ns=now,
                    kind="ROUTE_FAILED",
                    direction="RETURN",
                    request_sequence=sequence,
                    phase=_PHASE_ROUTING,
                    device_id=arrival.to_device_id,
                    facts={"target_ipv4": reply.destination},
                )
                self._fail_request(
                    runtime,
                    sequence,
                    outcome="FAILED",
                    code=decision.diagnostic_code or DiagnosticCode.RETURN_PATH_FAILURE,
                    direction="RETURN",
                    time_ns=now,
                    device_id=arrival.to_device_id,
                    forward_status="COMPLETED",
                    return_status="FAILED",
                )
                return
            next_hop_ip = decision.next_hop or reply.destination
            reply_packet = build_ipv4_packet(
                reply.source,
                reply.destination,
                reply,
                ttl=packet.ttl,
            )
            outbound = _Outbound(
                packet=reply_packet,
                from_interface_id=arrival.to_interface_id,
                next_hop_ip=next_hop_ip,
                request_sequence=sequence,
                direction="RETURN",
                packet_id=self._next_packet_id(runtime),
            )
            self._resolve_and_send(
                runtime,
                device_id=arrival.to_device_id,
                from_interface_id=arrival.to_interface_id,
                next_hop_ip=next_hop_ip,
                outbound=outbound,
                time_ns=now + ENDPOINT_ICMP_PROCESSING_NS,
            )
            return
        if runtime.source_ip is None:
            return
        correlation = RequestCorrelation(
            test_id=runtime.identifier,
            sequence=message.sequence,
            source=runtime.source_ip,
            destination=runtime.destination_ip,
        )
        if runtime.correlator.match(message, correlation) is not ReplyMatchOutcome.MATCHED:
            return
        match = self._emit(
            runtime,
            time_ns=now,
            kind="ICMP_ECHO_MATCHED",
            direction="RETURN",
            request_sequence=sequence,
            device_id=arrival.to_device_id,
            packet_id=arrival.packet_id,
            facts={"packet_type": "ECHO_REPLY"},
        )
        self._finish_request(
            runtime,
            sequence,
            outcome="SUCCESS",
            finalized_at_ns=now,
            matched_reply_event_id=match.event_id,
            forward_status="COMPLETED",
            return_status="COMPLETED",
        )

    # --- request lifecycle ----------------------------------------------------

    def _fail_request(
        self,
        runtime: _Runtime,
        sequence: int,
        *,
        outcome: str,
        code: DiagnosticCode,
        direction: str,
        time_ns: int,
        device_id: str | None = None,
        interface_id: str | None = None,
        classification: DiagnosticClassification = DiagnosticClassification.SIMULATION_FAILURE,
        forward_status: str | None = None,
        return_status: str | None = None,
    ) -> None:
        state = runtime.requests.get(sequence)
        if state is None or state.outcome is not None:
            return
        diagnostic_id = self._diagnose(
            runtime,
            code=code,
            request_sequence=sequence,
            direction=direction,
            time_ns=time_ns,
            device_id=device_id,
            interface_id=interface_id,
            classification=classification,
        )
        if forward_status is None:
            forward_status = "FAILED" if direction == "FORWARD" else "COMPLETED"
        if return_status is None:
            return_status = "FAILED" if direction in ("RETURN", "LOCAL") else "NOT_STARTED"
        self._finish_request(
            runtime,
            sequence,
            outcome=outcome,
            finalized_at_ns=time_ns,
            primary_diagnostic_id=diagnostic_id,
            forward_status=forward_status,
            return_status=return_status,
        )

    def _finish_request(
        self,
        runtime: _Runtime,
        sequence: int,
        *,
        outcome: str,
        finalized_at_ns: int,
        matched_reply_event_id: str | None = None,
        primary_diagnostic_id: str | None = None,
        forward_status: str | None = None,
        return_status: str | None = None,
        emit_event: bool = True,
    ) -> None:
        state = runtime.requests.get(sequence)
        if state is None or state.outcome is not None:
            return
        if emit_event:
            self._emit(
                runtime,
                time_ns=finalized_at_ns,
                kind="REQUEST_FINALIZED",
                direction="NONE",
                request_sequence=sequence,
                phase=_PHASE_OBSERVATION,
                facts={"reason_key": outcome},
            )
        runtime.requests[sequence] = _RequestState(
            sequence=sequence,
            started_at_ns=state.started_at_ns,
            emitted_at_ns=state.emitted_at_ns,
            finalized_at_ns=finalized_at_ns,
            outcome=outcome,
            matched_reply_event_id=matched_reply_event_id,
            primary_diagnostic_id=primary_diagnostic_id,
            forward_path_status=state.forward_path_status
            if forward_status is None
            else forward_status,
            return_path_status=state.return_path_status if return_status is None else return_status,
        )
        self._record_hops(runtime, sequence)

    def _record_hops(self, runtime: _Runtime, sequence: int) -> None:
        """Pair witnessed FRAME_TX/FRAME_ARRIVAL events into physical L2 hops."""
        if runtime.source_device_id == runtime.destination_device_id:
            return
        pending_tx: dict[tuple[str, str, str], list[EventEvidence]] = {}
        for event in runtime.events:
            if event.kind != "FRAME_TX" or event.request_sequence != sequence:
                continue
            if not event.frame_id or not event.connection_id or not event.egress_interface_id:
                continue
            key = (event.frame_id, event.direction, event.connection_id)
            pending_tx.setdefault(key, []).append(event)

        for arrival in runtime.events:
            if arrival.kind != "FRAME_ARRIVED" or arrival.request_sequence != sequence:
                continue
            if (
                not arrival.frame_id
                or not arrival.connection_id
                or not arrival.ingress_interface_id
            ):
                continue
            key = (arrival.frame_id, arrival.direction, arrival.connection_id)
            candidates = pending_tx.get(key)
            if not candidates:
                continue
            tx = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.virtual_time_ns <= arrival.virtual_time_ns
                ),
                None,
            )
            if tx is None:
                continue
            candidates.remove(tx)
            runtime.hop_index += 1
            runtime.hops.append(
                HopEvidence(
                    hop_id=f"hop-{runtime.hop_index:05d}",
                    packet_id=tx.packet_id or f"pkt-{sequence}",
                    frame_id=tx.frame_id or arrival.frame_id,
                    request_sequence=sequence,
                    direction=tx.direction,
                    from_device_id=tx.device_id or runtime.source_device_id,
                    to_device_id=arrival.device_id or runtime.destination_device_id,
                    egress_interface_id=tx.egress_interface_id,
                    ingress_interface_id=arrival.ingress_interface_id,
                    connection_id=tx.connection_id,
                    tx_start_ns=tx.virtual_time_ns,
                    rx_complete_ns=arrival.virtual_time_ns,
                    outcome="DELIVERED",
                    source_event_ids=(tx.event_id, arrival.event_id),
                )
            )

    def _simulate(
        self,
        project: Project,
        *,
        test_id: str,
        project_id: str,
        source_device_id: str,
        destination_device_id: str,
        snapshot_ref: dict[str, object],
    ) -> ResultEvidence:
        runtime = self._build_runtime(
            project,
            test_id=test_id,
            project_id=project_id,
            source_device_id=source_device_id,
            destination_device_id=destination_device_id,
            snapshot_ref=snapshot_ref,
        )
        started_at_ns = 0
        execution_status = "COMPLETED"
        observation_status = "COMPLETE"
        try:
            for sequence in range(1, REQUESTS_PLANNED + 1):
                runtime.queue.schedule(
                    (sequence - 1) * PING_DEADLINE_NS,
                    _PHASE_CONTROL,
                    _StartRequest(sequence),
                    branch_id=f"req-{sequence}",
                )
            while runtime.queue:
                executed = runtime.queue.pop()
                payload = executed.event.payload
                now = executed.event.virtual_time_ns
                if isinstance(payload, _StartRequest):
                    self._start_request(runtime, payload.sequence, now)
                elif isinstance(payload, _FrameArrival):
                    self._handle_frame_arrival(runtime, payload)
                elif isinstance(payload, _ArpDeadline):
                    self._handle_arp_deadline(runtime, payload)
                elif isinstance(payload, _RequestDeadline):
                    self._handle_request_deadline(runtime, payload.sequence, now)
        except EventBudgetExhausted as error:
            execution_status = "INCOMPLETE"
            observation_status = "NOT_STARTED"
            runtime.execution_limit_code = (
                DiagnosticCode.TEST_EVENT_BUDGET_EXHAUSTED
                if "test event budget" in str(error)
                else DiagnosticCode.REQUEST_EVENT_BUDGET_EXHAUSTED
            )
            self._limit_outstanding(runtime)
        except BranchTraversalLimitExceeded:
            execution_status = "INCOMPLETE"
            observation_status = "NOT_STARTED"
            runtime.execution_limit_code = DiagnosticCode.FRAME_BRANCH_TRAVERSAL_LIMIT
            self._limit_outstanding(runtime)

        finalizations = [
            state.finalized_at_ns
            for state in runtime.requests.values()
            if state.finalized_at_ns is not None
        ]
        last_finalization = max(finalizations) if finalizations else started_at_ns
        finalized_at_ns = max(
            last_finalization,
            runtime.events[-1].virtual_time_ns if runtime.events else 0,
        )
        self._emit(
            runtime,
            time_ns=finalized_at_ns,
            kind="TEST_FINALIZED",
            direction="NONE",
            phase=_PHASE_OBSERVATION,
        )
        self._emit(
            runtime,
            time_ns=finalized_at_ns,
            kind="OBSERVATION_CLOSED",
            direction="NONE",
            phase=_PHASE_OBSERVATION,
        )

        requests = tuple(
            RequestEvidence(
                outcome=state.outcome or "EXECUTION_LIMITED",
                started_at_ns=state.started_at_ns,
                finalized_at_ns=(
                    state.finalized_at_ns if state.finalized_at_ns is not None else finalized_at_ns
                ),
                emitted_at_ns=state.emitted_at_ns,
                matched_reply_event_id=state.matched_reply_event_id,
                primary_diagnostic_id=state.primary_diagnostic_id,
                forward_path_status=state.forward_path_status,
                return_path_status=state.return_path_status,
            )
            for sequence in range(1, len(runtime.requests) + 1)
            for state in [runtime.requests[sequence]]
        )
        return ResultEvidence(
            test_id=test_id,
            project_id=project_id,
            source_device_id=source_device_id,
            destination_device_id=destination_device_id,
            snapshot_ref=snapshot_ref,
            execution_status=execution_status,
            observation_status=observation_status,
            started_at_ns=started_at_ns,
            finalized_at_ns=finalized_at_ns,
            closed_at_ns=finalized_at_ns,
            icmp_identifier=runtime.identifier,
            requests=requests,
            events=tuple(runtime.events),
            diagnostics=tuple(runtime.diagnostics),
            hops=tuple(runtime.hops),
        )

    def _start_request(self, runtime: _Runtime, sequence: int, now: int) -> None:
        runtime.requests[sequence] = _RequestState(sequence=sequence, started_at_ns=now)
        runtime.queue.schedule(
            now + PING_DEADLINE_NS,
            _PHASE_FAILURE,
            _RequestDeadline(sequence),
            branch_id=f"req-{sequence}",
        )
        if runtime.source_device_id == runtime.destination_device_id:
            self._local_echo(runtime, sequence, now)
            return
        if runtime.source_ip is None or runtime.source_mask is None:
            self._fail_request(
                runtime,
                sequence,
                outcome="FAILED",
                code=DiagnosticCode.SOURCE_IPV4_UNCONFIGURED,
                direction="LOCAL",
                time_ns=now,
                device_id=runtime.source_device_id,
                forward_status="FAILED",
                return_status="NOT_STARTED",
            )
            return
        gateway = self._gateway_of(runtime, runtime.source_device_id)
        decision = decide_host_forwarding(
            runtime.destination_ip,
            source_address=runtime.source_ip,
            mask=runtime.source_mask,
            gateway=gateway,
        )
        facts: dict[str, object] = {"target_ipv4": runtime.destination_ip}
        if decision.next_hop is not None:
            facts["router_id"] = self._gateway_device(runtime, decision.next_hop)
        if not decision.is_usable:
            self._emit(
                runtime,
                time_ns=now,
                kind="ROUTE_FAILED",
                direction="FORWARD",
                request_sequence=sequence,
                phase=_PHASE_ROUTING,
                device_id=runtime.source_device_id,
                facts=facts,
            )
            self._fail_request(
                runtime,
                sequence,
                outcome="FAILED",
                code=decision.diagnostic_code or DiagnosticCode.NO_MATCHING_ROUTE,
                direction="FORWARD",
                time_ns=now,
                device_id=runtime.source_device_id,
                forward_status="FAILED",
                return_status="NOT_STARTED",
            )
            return
        self._emit(
            runtime,
            time_ns=now,
            kind="ROUTE_SELECTED",
            direction="FORWARD",
            request_sequence=sequence,
            phase=_PHASE_ROUTING,
            device_id=runtime.source_device_id,
            facts=facts,
        )
        echo = build_echo_request(
            runtime.source_ip,
            runtime.destination_ip,
            identifier=runtime.identifier,
            sequence=sequence,
        )
        packet = build_ipv4_packet(runtime.source_ip, runtime.destination_ip, echo)
        packet_id = self._next_packet_id(runtime)
        emitted = self._emit(
            runtime,
            time_ns=now,
            kind="ICMP_ECHO_EMITTED",
            direction="FORWARD",
            request_sequence=sequence,
            packet_id=packet_id,
            facts={"packet_type": "ECHO_REQUEST"},
        )
        runtime.requests[sequence] = replace(
            runtime.requests[sequence],
            emitted_at_ns=emitted.virtual_time_ns,
            forward_path_status="COMPLETED",
        )
        source_interface = self._egress_interface_for(
            runtime, runtime.source_device_id, decision.next_hop or runtime.destination_ip
        )
        if source_interface is None:
            self._fail_request(
                runtime,
                sequence,
                outcome="FAILED",
                code=DiagnosticCode.SOURCE_LINK_DOWN,
                direction="FORWARD",
                time_ns=now,
                device_id=runtime.source_device_id,
                forward_status="FAILED",
                return_status="NOT_STARTED",
            )
            return
        self._resolve_and_send(
            runtime,
            device_id=runtime.source_device_id,
            from_interface_id=source_interface,
            next_hop_ip=decision.next_hop or runtime.destination_ip,
            outbound=_Outbound(
                packet=packet,
                from_interface_id=source_interface,
                next_hop_ip=decision.next_hop or runtime.destination_ip,
                request_sequence=sequence,
                direction="FORWARD",
                packet_id=packet_id,
            ),
            time_ns=now,
        )

    def _local_echo(self, runtime: _Runtime, sequence: int, now: int) -> None:
        if runtime.source_ip is None:
            self._fail_request(
                runtime,
                sequence,
                outcome="FAILED",
                code=DiagnosticCode.SOURCE_IPV4_UNCONFIGURED,
                direction="LOCAL",
                time_ns=now,
                device_id=runtime.source_device_id,
                forward_status="FAILED",
                return_status="NOT_STARTED",
            )
            return
        echo = build_echo_request(
            runtime.source_ip,
            runtime.source_ip,
            identifier=runtime.identifier,
            sequence=sequence,
        )
        correlation = RequestCorrelation(
            test_id=runtime.identifier,
            sequence=sequence,
            source=runtime.source_ip,
            destination=runtime.source_ip,
        )
        self._emit(
            runtime,
            time_ns=now,
            kind="LOCAL_ECHO_PROCESSED",
            direction="LOCAL",
            request_sequence=sequence,
            device_id=runtime.source_device_id,
            facts={"packet_type": "ECHO_REQUEST"},
        )
        if runtime.correlator.match(echo.as_reply(), correlation) is not ReplyMatchOutcome.MATCHED:
            self._fail_request(
                runtime,
                sequence,
                outcome="FAILED",
                code=DiagnosticCode.ECHO_REPLY_MISMATCH,
                direction="LOCAL",
                time_ns=now,
                device_id=runtime.source_device_id,
                forward_status="FAILED",
                return_status="NOT_STARTED",
            )
            return
        emitted_at = now + ENDPOINT_ICMP_PROCESSING_NS // 2
        finalized_at = now + ENDPOINT_ICMP_PROCESSING_NS
        emitted = self._emit(
            runtime,
            time_ns=emitted_at,
            kind="ICMP_ECHO_EMITTED",
            direction="LOCAL",
            request_sequence=sequence,
            packet_id=self._next_packet_id(runtime),
            facts={"packet_type": "ECHO_REQUEST"},
        )
        runtime.requests[sequence] = replace(
            runtime.requests[sequence], emitted_at_ns=emitted.virtual_time_ns
        )
        match = self._emit(
            runtime,
            time_ns=finalized_at,
            kind="ICMP_ECHO_MATCHED",
            direction="RETURN",
            request_sequence=sequence,
            device_id=runtime.source_device_id,
            packet_id=emitted.packet_id,
            facts={"packet_type": "ECHO_REPLY"},
        )
        self._finish_request(
            runtime,
            sequence,
            outcome="SUCCESS",
            finalized_at_ns=finalized_at,
            matched_reply_event_id=match.event_id,
            forward_status="COMPLETED",
            return_status="COMPLETED",
        )

    def _handle_request_deadline(self, runtime: _Runtime, sequence: int, now: int) -> None:
        state = runtime.requests.get(sequence)
        if state is None or state.outcome is not None:
            return
        self._emit(
            runtime,
            time_ns=now,
            kind="ICMP_ECHO_TIMEOUT",
            direction="RETURN",
            request_sequence=sequence,
            phase=_PHASE_FAILURE,
            facts={"target_ipv4": runtime.destination_ip},
        )
        self._fail_request(
            runtime,
            sequence,
            outcome="TIMEOUT",
            code=DiagnosticCode.ECHO_TIMEOUT,
            direction="RETURN",
            time_ns=now,
            device_id=runtime.source_device_id,
            forward_status="COMPLETED" if state.emitted_at_ns is not None else "FAILED",
            return_status="FAILED",
        )

    def _limit_outstanding(self, runtime: _Runtime) -> None:
        """Close unfinished requests with a primary execution-limit diagnostic."""
        now = runtime.queue.now_ns
        last_event_ns = runtime.events[-1].virtual_time_ns if runtime.events else 0
        now = max(now, last_event_ns)
        for sequence in range(1, REQUESTS_PLANNED + 1):
            if sequence not in runtime.requests:
                runtime.requests[sequence] = _RequestState(
                    sequence=sequence, started_at_ns=(sequence - 1) * PING_DEADLINE_NS
                )
        for sequence, state in list(runtime.requests.items()):
            if state.outcome is not None:
                continue
            finalized = min(max(now, state.started_at_ns), state.started_at_ns + PING_DEADLINE_NS)
            diagnostic_id = self._diagnose(
                runtime,
                code=runtime.execution_limit_code or DiagnosticCode.REQUEST_EVENT_BUDGET_EXHAUSTED,
                request_sequence=sequence,
                direction="NONE",
                time_ns=now,
                classification=DiagnosticClassification.EXECUTION_LIMIT,
                completeness=EvidenceCompleteness.PARTIAL,
                facts={
                    "budget_limit": self._request_event_budget,
                    "budget_consumed": runtime.queue.request_events_scheduled,
                },
            )
            self._emit(
                runtime,
                time_ns=now,
                kind="EXECUTION_LIMIT_REACHED",
                direction="NONE",
                request_sequence=sequence,
                phase=_PHASE_FAILURE,
                facts={
                    "budget_limit": self._request_event_budget,
                    "budget_consumed": runtime.queue.request_events_scheduled,
                },
            )
            self._finish_request(
                runtime,
                sequence,
                outcome="EXECUTION_LIMITED",
                finalized_at_ns=finalized,
                primary_diagnostic_id=diagnostic_id,
                forward_status=state.forward_path_status,
                return_status=state.return_path_status,
                emit_event=False,
            )

    def _gateway_of(self, runtime: _Runtime, device_id: str) -> int | None:
        gateway = runtime.device_by_id[device_id].default_gateway_ipv4
        return None if gateway is None else parse_ipv4(gateway)

    @staticmethod
    def _gateway_device(runtime: _Runtime, address: int) -> str | None:
        entry = runtime.addresses.get(address)
        return None if entry is None else entry[1]

    @staticmethod
    def _egress_interface_for(runtime: _Runtime, device_id: str, next_hop: int) -> str | None:
        candidates = [
            interface
            for interface in runtime.interface_by_id.values()
            if interface.device_id == device_id
            and interface.ipv4 is not None
            and interface.admin_state is AdminState.ENABLED
        ]
        if not candidates:
            return None
        selected = next(
            (
                interface
                for interface in candidates
                if next_hop & prefix_mask(interface.ipv4.prefix_length)
                == parse_ipv4(interface.ipv4.address) & prefix_mask(interface.ipv4.prefix_length)
            ),
            None,
        )
        interface = selected or candidates[0]
        return (
            interface.interface_id
            if runtime.operational.get(interface.interface_id, False)
            else None
        )


__all__ = ["SimulatedPingRunner"]
