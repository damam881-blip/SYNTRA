"""Phase 3: event-driven Ping simulation over frozen TASK-04 topologies.

Every result returned by the runner is checked against the frozen TASK-05 JSON
Schema and the read-only ``verify_contract.check()`` oracle. Reference fixtures
are used only as simulation inputs and behavioural oracles; no reference file is
modified.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from app.db.document import configuration_projection
from app.engine.diagnostics.codes import DiagnosticCode
from app.engine.icmp.messages import EchoMessage
from app.engine.ping import SimulatedPingRunner
from app.engine.ping.result import DEFAULT_ICMP_IDENTIFIER

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "contracts" / "reference" / "task04" / "fixtures"
TASK05 = ROOT / "contracts" / "reference" / "task05"
SNAPSHOT_ID = "019a5000-0000-7000-8000-000000000004"
TEST_ID = "019a5000-0000-7000-8000-000000000099"
SOURCE_IP = "192.168.10.10"

_SCHEMA = json.loads((TASK05 / "schemas" / "task05-contract-v1.schema.json").read_text())
Draft202012Validator.check_schema(_SCHEMA)
SCHEMA_VALIDATOR = Draft202012Validator(_SCHEMA)


def _load_verifier() -> Any:
    path = TASK05 / "tools" / "verify_contract.py"
    spec = importlib.util.spec_from_file_location("task05_verify_contract_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = _load_verifier()


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _replay_input(document: Mapping[str, Any]) -> dict[str, Any]:
    """Reproduce the verified projection handed to the runner by the API."""
    return {
        "snapshot_id": SNAPSHOT_ID,
        "base_state_revision": document["project"]["state_revision"],
        "base_simulation_revision": document["project"]["simulation_revision"],
        "schema_version": "1.0.0",
        "configuration_digest": "a" * 64,
        "configuration": configuration_projection(document),
    }


def _endpoints(document: Mapping[str, Any]) -> tuple[str, str]:
    endpoints = [
        interface["device_id"]
        for interface in document["interfaces"]
        if interface.get("ipv4")
        and next(
            device
            for device in document["devices"]
            if device["device_id"] == interface["device_id"]
        )["kind"]
        in ("PC", "SERVER")
    ]
    return endpoints[0], endpoints[-1]


def _device_with_ip(document: Mapping[str, Any], address: str) -> str:
    return next(
        interface["device_id"]
        for interface in document["interfaces"]
        if (interface.get("ipv4") or {}).get("address") == address
    )


def _assert_valid(document: Mapping[str, Any]) -> None:
    errors = [error.message for error in SCHEMA_VALIDATOR.iter_errors(document)]
    assert not errors, f"SCHEMA: {errors[:3]}"
    assert VERIFIER.check(document) == []


def _run(
    name: str,
    *,
    runner: SimulatedPingRunner | None = None,
    mutate: Callable[[dict[str, Any]], None] | None = None,
    source_ip: str = SOURCE_IP,
    destination: str | None = None,
    self_ping: bool = False,
) -> dict[str, object]:
    document = _load_fixture(name)
    replay = _replay_input(document)
    if mutate is not None:
        mutate(replay)
    source = _device_with_ip(document, source_ip)
    destination_id = (
        source
        if self_ping
        else (UUID(destination) if destination is not None else _endpoints(document)[1])
    )
    result = (runner or SimulatedPingRunner()).run(
        replay,
        test_id=UUID(TEST_ID),
        project_id=UUID(replay["configuration"]["project"]["project_id"]),
        source_device_id=UUID(source),
        destination_device_id=UUID(destination_id),
    )
    _assert_valid(result)
    return result


def _disconnect_destination(replay: dict[str, Any]) -> None:
    document = _load_fixture("rt-01")
    destination = _endpoints(document)[1]
    interfaces = {
        interface["interface_id"]
        for interface in document["interfaces"]
        if interface["device_id"] == destination
    }
    replay["configuration"]["connections"] = [
        connection
        for connection in replay["configuration"]["connections"]
        if connection["interface_a_id"] not in interfaces
        and connection["interface_b_id"] not in interfaces
    ]


def _disconnect_source(replay: dict[str, Any]) -> None:
    document = _load_fixture("rt-01")
    source = _endpoints(document)[0]
    interfaces = {
        interface["interface_id"]
        for interface in document["interfaces"]
        if interface["device_id"] == source
    }
    replay["configuration"]["connections"] = [
        connection
        for connection in replay["configuration"]["connections"]
        if connection["interface_a_id"] not in interfaces
        and connection["interface_b_id"] not in interfaces
    ]


def _disable_router_egress(replay: dict[str, Any]) -> None:
    for interface in replay["configuration"]["interfaces"]:
        if (interface.get("ipv4") or {}).get("address") == "192.168.20.1":
            interface["admin_state"] = "DISABLED"


def _remove_source_gateway(replay: dict[str, Any]) -> None:
    source = _device_with_ip(_load_fixture("rt-03"), SOURCE_IP)
    for device in replay["configuration"]["devices"]:
        if device["device_id"] == source:
            device["default_gateway_ipv4"] = None


def _remove_destination_gateway(replay: dict[str, Any]) -> None:
    destination = _endpoints(_load_fixture("rt-03"))[1]
    for device in replay["configuration"]["devices"]:
        if device["device_id"] == destination:
            device["default_gateway_ipv4"] = None


class _IntermittentRunner(SimulatedPingRunner):
    """Test-only fault injection: drop the third echo request at the destination."""

    def _deliver_icmp(self, runtime: Any, arrival: Any, packet: Any, now: int) -> None:
        if (
            arrival.request_sequence == 3
            and isinstance(packet.payload, EchoMessage)
            and packet.payload.is_request
        ):
            self._fail_request(
                runtime,
                3,
                outcome="FAILED",
                code=DiagnosticCode.ECHO_REQUEST_DROPPED,
                direction="FORWARD",
                time_ns=now,
                device_id=arrival.to_device_id,
                forward_status="COMPLETED",
                return_status="FAILED",
            )
            return
        super()._deliver_icmp(runtime, arrival, packet, now)


@pytest.mark.parametrize("fixture", ["rt-01", "rt-02"])
def test_direct_l2_success(fixture: str) -> None:
    result = _run(fixture)
    assert result["execution_status"] == "COMPLETED"
    assert result["aggregate_outcome"] == "SUCCESS"
    assert result["statistics"]["replies_received"] == 4
    assert result["hop_evidence"]
    assert result["diagnostics"] == []
    assert all(
        row["icmp_identifier"] == DEFAULT_ICMP_IDENTIFIER for row in result["request_results"]
    )


def test_one_router_success() -> None:
    result = _run("rt-03")
    assert result["aggregate_outcome"] == "SUCCESS"
    kinds = {event["kind"] for event in result["events"]}
    assert {"ROUTE_SELECTED", "ARP_RESOLUTION", "ICMP_ECHO_MATCHED"} <= kinds
    assert result["statistics"]["rtt_avg_ns_rounded"] is not None


def test_two_router_multihop_success() -> None:
    result = _run("rt-04")
    assert result["aggregate_outcome"] == "SUCCESS"
    router_events = [event for event in result["events"] if event["kind"] == "ROUTE_SELECTED"]
    assert len(router_events) >= 8
    assert result["statistics"]["replies_received"] == 4


def test_missing_return_route() -> None:
    result = _run("rt-05")
    assert result["aggregate_outcome"] == "FAILURE"
    assert all(row["outcome"] == "FAILED" for row in result["request_results"])
    diagnostics = result["diagnostics"]
    assert diagnostics
    assert all(
        diagnostic["code"] == DiagnosticCode.NO_MATCHING_ROUTE.value
        and diagnostic["direction"] == "RETURN"
        for diagnostic in diagnostics
    )


def test_arp_no_response() -> None:
    result = _run("rt-01", mutate=_disconnect_destination)
    assert result["aggregate_outcome"] == "FAILURE"
    assert all(
        diagnostic["code"] == DiagnosticCode.ARP_NO_RESPONSE.value
        for diagnostic in result["diagnostics"]
    )


def test_no_route() -> None:
    result = _run("rt-03", mutate=_remove_source_gateway)
    assert result["aggregate_outcome"] == "FAILURE"
    assert all(
        diagnostic["code"] == DiagnosticCode.MISSING_DEFAULT_GATEWAY.value
        for diagnostic in result["diagnostics"]
    )


def test_source_link_down() -> None:
    result = _run("rt-01", mutate=_disconnect_source)
    assert result["aggregate_outcome"] == "FAILURE"
    assert all(
        diagnostic["code"] == DiagnosticCode.SOURCE_LINK_DOWN.value
        for diagnostic in result["diagnostics"]
    )


def test_no_eligible_route() -> None:
    result = _run("rt-03", mutate=_disable_router_egress)
    assert result["aggregate_outcome"] == "FAILURE"
    assert any(
        diagnostic["code"] == DiagnosticCode.NO_ELIGIBLE_ROUTE.value
        for diagnostic in result["diagnostics"]
    )


def test_return_path_failure() -> None:
    result = _run("rt-03", mutate=_remove_destination_gateway)
    assert result["aggregate_outcome"] == "FAILURE"
    assert any(
        diagnostic["code"] == DiagnosticCode.MISSING_DEFAULT_GATEWAY.value
        for diagnostic in result["diagnostics"]
    )


def test_self_ping() -> None:
    result = _run("rt-01", self_ping=True)
    assert result["aggregate_outcome"] == "SUCCESS"
    assert result["hop_evidence"] == []
    assert any(event["kind"] == "LOCAL_ECHO_PROCESSED" for event in result["events"])


def test_timeout_when_arp_window_exceeds_deadline() -> None:
    runner = SimulatedPingRunner(arp_window_ns=3_000_000_000)
    result = _run("rt-01", runner=runner, mutate=_disconnect_destination)
    assert any(row["outcome"] == "TIMEOUT" for row in result["request_results"])
    assert any(
        diagnostic["code"] == DiagnosticCode.ECHO_TIMEOUT.value
        for diagnostic in result["diagnostics"]
    )


def test_partial_success_from_injected_mid_run_fault() -> None:
    result = _run("rt-01", runner=_IntermittentRunner())
    assert result["aggregate_outcome"] == "PARTIAL_SUCCESS"
    assert [row["outcome"] for row in result["request_results"]].count("SUCCESS") == 3
    assert any(
        diagnostic["code"] == DiagnosticCode.ECHO_REQUEST_DROPPED.value
        for diagnostic in result["diagnostics"]
    )


@pytest.mark.parametrize("budget", [1, 5, 20])
def test_incomplete_under_event_budget_exhaustion(budget: int) -> None:
    result = _run("rt-01", runner=SimulatedPingRunner(request_event_budget=budget))
    assert result["execution_status"] == "INCOMPLETE"
    assert result["aggregate_outcome"] is None
    assert result["observation_status"] == "NOT_STARTED"
    assert len(result["request_results"]) == 4
    assert any(row["outcome"] == "EXECUTION_LIMITED" for row in result["request_results"])
    assert all(
        row["outcome"] in {"SUCCESS", "EXECUTION_LIMITED"} for row in result["request_results"]
    )
    assert all(
        diagnostic["code"] == DiagnosticCode.REQUEST_EVENT_BUDGET_EXHAUSTED.value
        for diagnostic in result["diagnostics"]
    )
    assert any(event["kind"] == "EXECUTION_LIMIT_REACHED" for event in result["events"])


def test_test_event_budget_uses_test_budget_diagnostic() -> None:
    result = _run("rt-01", runner=SimulatedPingRunner(test_event_budget=20))
    assert result["execution_status"] == "INCOMPLETE"
    assert all(
        diagnostic["code"] == DiagnosticCode.TEST_EVENT_BUDGET_EXHAUSTED.value
        for diagnostic in result["diagnostics"]
    )


def test_runner_is_deterministic() -> None:
    first = _run("rt-04")
    second = _run("rt-04")
    assert first == second


def test_runner_rejects_command_project_mismatch() -> None:
    document = _load_fixture("rt-01")
    replay = _replay_input(document)
    source = _device_with_ip(document, SOURCE_IP)
    destination = _endpoints(document)[1]

    with pytest.raises(ValueError, match="snapshot project does not match the command"):
        SimulatedPingRunner().run(
            replay,
            test_id=UUID(TEST_ID),
            project_id=UUID("019a5000-0000-7000-8000-000000000009"),
            source_device_id=UUID(source),
            destination_device_id=UUID(destination),
        )
