"""Public surface of the TASK-06 evidence and retention service."""

from app.modules.logs.service import (
    accept_ping_command,
    canonical_contract_bytes,
    get_ping_result,
    load_retention_policy,
    purge_expired,
    record_error_envelope,
    record_ping_result,
)

__all__ = [
    "accept_ping_command",
    "canonical_contract_bytes",
    "get_ping_result",
    "load_retention_policy",
    "purge_expired",
    "record_error_envelope",
    "record_ping_result",
]
