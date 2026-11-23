"""Phase 1: the TASK-07 §8.2 PingRunner port keeps its approved signature."""

from __future__ import annotations

import inspect
from typing import get_type_hints
from uuid import UUID

from app.engine.ping import PingRunner


class _CompliantRunner:
    def run(
        self,
        replay_input: dict[str, object],
        *,
        test_id: UUID,
        project_id: UUID,
        source_device_id: UUID,
        destination_device_id: UUID,
    ) -> dict[str, object]:
        return {}


class _NoRun:
    pass


def test_protocol_signature_matches_task07_section_8_2():
    parameters = inspect.signature(PingRunner.run).parameters
    assert list(parameters) == [
        "self",
        "replay_input",
        "test_id",
        "project_id",
        "source_device_id",
        "destination_device_id",
    ]
    assert parameters["replay_input"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    for name in ("test_id", "project_id", "source_device_id", "destination_device_id"):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert get_type_hints(PingRunner.run)["return"] == dict[str, object]


def test_protocol_is_structural_and_runtime_checkable():
    assert isinstance(_CompliantRunner(), PingRunner)
    assert not isinstance(_NoRun(), PingRunner)


def test_protocol_is_pure_python_without_persistence_methods():
    assert not hasattr(PingRunner, "commit")
    assert not hasattr(PingRunner, "session")
