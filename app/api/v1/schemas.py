"""Strict TASK-07 API schemas (§14.2 step 2).

This module defines data shapes only: request DTOs, the generic response
envelope, ``ApiMeta`` and the error envelope. It deliberately does **not**
define ``ProjectStateDocument`` or ``PingTestResult``: §11.4 requires those
nested documents to be checked against the frozen JSON Schema references in
contract tests instead of being duplicated (and potentially weakened) in a
second Python model.

No router, dependency, database session or exception mapping is wired here.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.db.enums import AdminState, CableType, DeviceKind
from app.engine.ipv4.address import InvalidIPv4AddressError, parse_ipv4

# §11.4: nested canonical documents are validated against the reference JSON
# Schemas in contract tests, not re-declared field by field here.
CanonicalDocument = dict[str, Any]


def _require_uuid7(value: UUID) -> UUID:
    """Reject any identifier that is not a canonical RFC 4122 UUIDv7."""
    if value.version != 7:
        raise ValueError("identifier must be a UUIDv7")
    return value


UUIDv7 = Annotated[UUID, AfterValidator(_require_uuid7)]


def _require_canonical_ipv4(value: str) -> str:
    """Reject non-ASCII digits, leading zeros and anything but four octets."""
    try:
        parse_ipv4(value)
    except InvalidIPv4AddressError as error:
        raise ValueError(str(error)) from error
    return value


IPv4Text = Annotated[str, AfterValidator(_require_canonical_ipv4)]


class StrictModel(BaseModel):
    """Shared request/response base: unknown fields are rejected (§11.1)."""

    model_config = ConfigDict(extra="forbid")


class ApiMeta(StrictModel):
    """Envelope metadata shared by every API response (§11.2 + DEC-07-003)."""

    api_version: Literal["v1"] = "v1"
    request_id: str | None = None
    command_id: UUIDv7 | None = None
    evidence_freshness: Literal["CURRENT", "STALE"] | None = None
    result_base_simulation_revision: int | None = None
    current_simulation_revision: int | None = None
    is_current: bool | None = None

    @model_validator(mode="after")
    def _freshness_invariant(self) -> ApiMeta:
        """``is_current`` must mirror ``evidence_freshness`` (DEC-07-003)."""
        freshness = self.evidence_freshness
        expected = None if freshness is None else freshness == "CURRENT"
        if self.is_current is not expected:
            raise ValueError("is_current must match evidence_freshness")
        return self

    @classmethod
    def for_ping(
        cls,
        *,
        base_simulation_revision: int,
        current_simulation_revision: int,
        request_id: str | None = None,
        command_id: UUID | None = None,
    ) -> ApiMeta:
        """Build read-time Ping freshness metadata from the two revisions."""
        freshness = (
            "CURRENT" if base_simulation_revision == current_simulation_revision else "STALE"
        )
        return cls(
            request_id=request_id,
            command_id=command_id,
            evidence_freshness=freshness,
            result_base_simulation_revision=base_simulation_revision,
            current_simulation_revision=current_simulation_revision,
            is_current=freshness == "CURRENT",
        )


class ApiEnvelope[T](StrictModel):
    """Successful responses: ``data`` plus ``meta`` (§11.2, §11.4)."""

    data: T
    meta: ApiMeta


ProjectEnvelope = ApiEnvelope[CanonicalDocument]
PingEnvelope = ApiEnvelope[CanonicalDocument]


class CheckpointReceipt(StrictModel):
    """Dedicated receipt for checkpoint saves (§7.1, §11.4); revisions unchanged."""

    checkpoint_id: UUIDv7
    project_id: UUIDv7
    revision: int
    label: str | None = None
    created_at: str


class DeletionReceipt(StrictModel):
    """Dedicated receipt built from the tombstone, not the purged document (§7.1)."""

    project_id: UUIDv7
    project_name: str
    last_state_revision: int
    last_simulation_revision: int
    deleted_by: str
    deleted_at: str


CheckpointReceiptEnvelope = ApiEnvelope[CheckpointReceipt]
DeletionReceiptEnvelope = ApiEnvelope[DeletionReceipt]


class ProjectSummary(StrictModel):
    """List-view projection (§7.1, D7-07): no child collections, no counters."""

    project_id: UUIDv7
    name: str
    description: str | None = None
    state_revision: int
    simulation_revision: int
    created_at: str
    updated_at: str


ProjectListEnvelope = ApiEnvelope[list[ProjectSummary]]
CollectionEnvelope = ApiEnvelope[list[CanonicalDocument]]
DeviceEnvelope = ApiEnvelope[CanonicalDocument]


# ---------------------------------------------------------------------------
# Request DTOs — §7 endpoint payloads and §11.2 shape draft
# ---------------------------------------------------------------------------


class ProjectCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)


class DeleteProjectRequest(StrictModel):
    """DELETE body; ``confirm_name`` must match the stored name exactly (§7.1)."""

    confirm_name: str = Field(min_length=1, max_length=64)


class CheckpointCreateRequest(StrictModel):
    label: str | None = Field(default=None, max_length=120)


class PositionIn(StrictModel):
    x: float
    y: float
    z: float


class DeviceCreateRequest(StrictModel):
    kind: DeviceKind
    display_name: str = Field(min_length=1, max_length=64)
    position: PositionIn | None = None
    rotation_y_degrees: float = Field(default=0.0, ge=-180, lt=180)


class DeviceRenameRequest(StrictModel):
    display_name: str = Field(min_length=1, max_length=64)


class DevicePositionRequest(StrictModel):
    position: PositionIn


class RotationRequest(StrictModel):
    rotation_y_degrees: float = Field(ge=-180, lt=180)


class AdminStateRequest(StrictModel):
    admin_state: AdminState


class InterfaceIPv4Request(StrictModel):
    address: IPv4Text
    prefix_length: int = Field(ge=1, le=30)


class GatewayRequest(StrictModel):
    gateway_ipv4: IPv4Text


class ConnectionCreateRequest(StrictModel):
    interface_a_id: UUIDv7
    interface_b_id: UUIDv7
    cable_type: CableType
    # Distinctness/occupancy stays in the service (§7.4, §9.4).


class StaticRouteCreateRequest(StrictModel):
    router_device_id: UUIDv7
    destination_network: IPv4Text
    prefix_length: int = Field(ge=0, le=32)
    next_hop_ipv4: IPv4Text


class StaticRoutePatchRequest(StrictModel):
    destination_network: IPv4Text | None = None
    prefix_length: int | None = Field(default=None, ge=0, le=32)
    next_hop_ipv4: IPv4Text | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> StaticRoutePatchRequest:
        if all(
            value is None
            for value in (
                self.destination_network,
                self.prefix_length,
                self.next_hop_ipv4,
            )
        ):
            raise ValueError("at least one editable static-route field is required")
        return self


class PingCreateRequest(StrictModel):
    """Unity owns ``test_id``; the backend validates it as the idempotency key."""

    test_id: UUIDv7
    source_device_id: UUIDv7
    destination_device_id: UUIDv7


# ---------------------------------------------------------------------------
# Error models — preserve the existing outer envelope (§9.1)
# ---------------------------------------------------------------------------


class ValidationIssue(StrictModel):
    loc: list[str | int]
    msg: str
    type: str


class StaleStateDetails(StrictModel):
    expected_state_revision: int
    current_state_revision: int
    current_simulation_revision: int


class ErrorDetail(StrictModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorEnvelope(StrictModel):
    error: ErrorDetail
