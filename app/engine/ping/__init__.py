"""Real Ping simulation runner (TASK-07 §8.2: boundary, adapter, assembler, core)."""

from __future__ import annotations

from app.engine.ping.protocol import PingRunner, PingRunnerInput, PingRunnerResult
from app.engine.ping.result import (
    CONTRACT_VERSION,
    DEFAULT_ICMP_IDENTIFIER,
    DiagnosticEvidence,
    EventEvidence,
    HopEvidence,
    RequestEvidence,
    ResultAssemblyError,
    ResultEvidence,
    assemble_result,
)
from app.engine.ping.runner import SimulatedPingRunner
from app.engine.ping.topology import (
    InvalidReplayInputError,
    ReplaySnapshot,
    parse_replay_input,
    topology_from_replay_input,
)

__all__ = [
    "CONTRACT_VERSION",
    "DEFAULT_ICMP_IDENTIFIER",
    "DiagnosticEvidence",
    "EventEvidence",
    "HopEvidence",
    "InvalidReplayInputError",
    "PingRunner",
    "PingRunnerInput",
    "PingRunnerResult",
    "ReplaySnapshot",
    "RequestEvidence",
    "ResultAssemblyError",
    "ResultEvidence",
    "SimulatedPingRunner",
    "assemble_result",
    "parse_replay_input",
    "topology_from_replay_input",
]
