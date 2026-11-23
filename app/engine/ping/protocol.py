"""Ping execution boundary proposed by TASK-07 §8.2 (decision D7-10).

The API owns command/snapshot acceptance and immutable result persistence; the
engine owns simulation only. ``PingRunner`` is therefore a narrow, synchronous
port: it receives the verified output of ``replay_input(snapshot)`` plus the
four identities supplied by the accepted command, and returns one complete
TASK-05 ``PingTestResult`` document.

A runner implementation must not write to a database, change topology, read
wall-clock time or emit a result that has not been produced by simulating the
frozen configuration. No implementation is provided in this module.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

PingRunnerInput = dict[str, object]
"""Verified replay input: snapshot identity/digest/revisions + frozen configuration."""

PingRunnerResult = dict[str, object]
"""One complete, immutable TASK-05 PingTestResult document."""


@runtime_checkable
class PingRunner(Protocol):
    """Synchronous Ping simulation port (TASK-07 §8.2 signature, verbatim)."""

    def run(
        self,
        replay_input: PingRunnerInput,
        *,
        test_id: UUID,
        project_id: UUID,
        source_device_id: UUID,
        destination_device_id: UUID,
    ) -> PingRunnerResult:
        """Return one complete TASK-05 PingTestResult document.

        The input is the isolated output of ``replay_input(snapshot)``. The
        implementation must not write to PostgreSQL and must not change the
        topology it was given.
        """
        ...


__all__ = ["PingRunner", "PingRunnerInput", "PingRunnerResult"]
