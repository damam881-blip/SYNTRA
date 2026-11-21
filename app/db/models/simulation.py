"""TASK-05 simulation contract persistence models.
Scalar fields are relational.  The contract's ordered evidence arrays
(statistics, request_results, diagnostics, events, hop_evidence and derived
warnings) are stored as JSONB exactly as received, together with the canonical
UTF-8 JSON and its SHA-256.  This is the TASK-06 handoff requirement: retrieved
bytes must preserve the immutable result and the exact snapshot reference.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    non_negative_check,
    positive_check,
    uuid7_check,
)
from app.db.enums import (
    AggregateOutcome,
    ErrorClass,
    ErrorReason,
    ExecutionStatus,
    ObservationStatus,
)
from app.db.pgtypes import (
    AGGREGATE_OUTCOME,
    ERROR_CLASS,
    ERROR_REASON,
    EXECUTION_STATUS,
    OBSERVATION_STATUS,
)


class SnapshotRef(Base):
    __tablename__ = "snapshot_ref"
    snapshot_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"), nullable=False
    )
    base_state_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    base_simulation_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    configuration_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        uuid7_check("snapshot_id", "snapshot_id_uuid7"),
        UniqueConstraint("project_id", "snapshot_id", name="uq_snapshot_project_snapshot"),
        positive_check("base_state_revision", "base_state_revision_positive"),
        positive_check("base_simulation_revision", "base_simulation_revision_positive"),
        CheckConstraint(
            "base_simulation_revision <= base_state_revision",
            name="simulation_revision_not_ahead",
        ),
        CheckConstraint("configuration_digest ~ '^[0-9a-f]{64}$'", name="digest_sha256"),
        CheckConstraint("schema_version <> ''", name="schema_version_not_blank"),
        CheckConstraint(
            "jsonb_typeof(configuration_json) = 'object'",
            name="configuration_object",
        ),
    )


class PingTestCommand(Base):
    __tablename__ = "ping_test_command"
    command_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    contract_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    test_id: Mapped[uuid.UUID] = mapped_column(nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_device_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    destination_device_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    test_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="PING")
    expected_echo_requests: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=4)
    initial_runtime_state: Mapped[str] = mapped_column(String(20), nullable=False, default="FRESH")
    snapshot_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    result: Mapped[PingTestResult | None] = relationship(
        back_populates="command", uselist=False, passive_deletes=True
    )
    __table_args__ = (
        uuid7_check("command_id", "command_id_uuid7"),
        uuid7_check("test_id", "test_id_uuid7"),
        uuid7_check("source_device_id", "source_device_id_uuid7"),
        uuid7_check("destination_device_id", "destination_device_id_uuid7"),
        uuid7_check("snapshot_id", "command_snapshot_id_uuid7"),
        ForeignKeyConstraint(
            ["project_id"],
            ["project.project_id"],
            ondelete="CASCADE",
            name="fk_ping_command_project",
        ),
        ForeignKeyConstraint(
            ["project_id", "snapshot_id"],
            ["snapshot_ref.project_id", "snapshot_ref.snapshot_id"],
            ondelete="CASCADE",
            name="fk_ping_command_snapshot",
        ),
        UniqueConstraint("project_id", "test_id", name="uq_ping_command_project_test"),
        CheckConstraint("contract_version <> ''", name="contract_version_not_blank"),
        CheckConstraint("test_kind = 'PING'", name="test_kind_ping"),
        CheckConstraint("expected_echo_requests = 4", name="expected_echo_requests"),
        CheckConstraint("initial_runtime_state = 'FRESH'", name="initial_runtime_state_fresh"),
    )


class PingTestResult(Base):
    __tablename__ = "ping_test_result"
    test_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    contract_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_device_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    destination_device_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(20), nullable=False, default="CLOSED")
    execution_status: Mapped[ExecutionStatus] = mapped_column(EXECUTION_STATUS, nullable=False)
    aggregate_outcome: Mapped[AggregateOutcome | None] = mapped_column(AGGREGATE_OUTCOME)
    observation_status: Mapped[ObservationStatus] = mapped_column(
        OBSERVATION_STATUS, nullable=False
    )
    started_at_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    finalized_at_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    closed_at_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    statistics_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_results_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    diagnostics_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    events_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    hop_evidence_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    derived_warning_evidence_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    command: Mapped[PingTestCommand] = relationship(back_populates="result")
    __table_args__ = (
        uuid7_check("test_id", "result_test_id_uuid7"),
        uuid7_check("snapshot_id", "result_snapshot_id_uuid7"),
        ForeignKeyConstraint(
            ["project_id"],
            ["project.project_id"],
            ondelete="CASCADE",
            name="fk_ping_result_project",
        ),
        ForeignKeyConstraint(
            ["test_id"],
            ["ping_test_command.test_id"],
            ondelete="CASCADE",
            name="fk_ping_result_command",
        ),
        ForeignKeyConstraint(
            ["project_id", "snapshot_id"],
            ["snapshot_ref.project_id", "snapshot_ref.snapshot_id"],
            ondelete="CASCADE",
            name="fk_ping_result_snapshot",
        ),
        non_negative_check("started_at_ns", "started_at_ns_non_negative"),
        non_negative_check("finalized_at_ns", "finalized_at_ns_non_negative"),
        non_negative_check("closed_at_ns", "closed_at_ns_non_negative"),
        CheckConstraint("lifecycle = 'CLOSED'", name="lifecycle_closed"),
        CheckConstraint("contract_version <> ''", name="contract_version_not_blank"),
        CheckConstraint("jsonb_typeof(statistics_json) = 'object'", name="statistics_object"),
        CheckConstraint(
            "jsonb_typeof(request_results_json) = 'array' "
            "AND jsonb_array_length(request_results_json) <= 4",
            name="request_results_array",
        ),
        CheckConstraint("jsonb_typeof(diagnostics_json) = 'array'", name="diagnostics_array"),
        CheckConstraint(
            "jsonb_typeof(events_json) = 'array' AND jsonb_array_length(events_json) <= 40000",
            name="events_array",
        ),
        CheckConstraint("jsonb_typeof(hop_evidence_json) = 'array'", name="hop_evidence_array"),
        CheckConstraint(
            "jsonb_typeof(derived_warning_evidence_json) = 'array'",
            name="warnings_array",
        ),
        CheckConstraint("result_sha256 ~ '^[0-9a-f]{64}$'", name="result_sha256"),
    )


class ErrorEnvelope(Base):
    __tablename__ = "error_envelope"
    error_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    contract_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE")
    )
    test_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ping_test_command.test_id", ondelete="NO ACTION")
    )
    error_class: Mapped[ErrorClass] = mapped_column(ERROR_CLASS, nullable=False)
    code: Mapped[ErrorReason] = mapped_column(ERROR_REASON, nullable=False)
    message_key: Mapped[str] = mapped_column(String(128), nullable=False)
    details_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column()
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        uuid7_check("error_id", "error_id_uuid7"),
        CheckConstraint("contract_version <> ''", name="contract_version_not_blank"),
        CheckConstraint("length(message_key) >= 1", name="message_key_not_empty"),
        CheckConstraint("jsonb_typeof(details_json) = 'array'", name="details_array"),
        CheckConstraint("canonical_sha256 ~ '^[0-9a-f]{64}$'", name="canonical_sha256"),
        CheckConstraint(
            "("
            "(error_class = 'COMMAND_INVALID' AND code IN "
            "('MALFORMED_PING_COMMAND','INVALID_COMMAND_FIELD')) OR "
            "(error_class = 'REFERENCE_INVALID' AND code IN "
            "('UNKNOWN_PROJECT','UNKNOWN_SOURCE_DEVICE','UNKNOWN_DESTINATION_DEVICE',"
            "'UNSUPPORTED_PING_SOURCE','UNSUPPORTED_PING_DESTINATION',"
            "'CROSS_PROJECT_REFERENCE')) OR "
            "(error_class = 'SNAPSHOT_INVALID' AND code IN "
            "('MISSING_SNAPSHOT','SNAPSHOT_REVISION_MISMATCH',"
            "'SNAPSHOT_DIGEST_MISMATCH')) OR "
            "(error_class = 'VERSION_UNSUPPORTED' AND code IN "
            "('UNSUPPORTED_MODEL_SCHEMA_VERSION','UNSUPPORTED_CONTRACT_VERSION')) OR "
            "(error_class = 'PRECONDITION_CONFLICT' AND code = "
            "'REQUEST_PRECONDITION_CONFLICT') OR "
            "(error_class = 'PERSISTENCE_FAILURE' AND code = "
            "'PERSISTENCE_UNAVAILABLE') OR "
            "(error_class = 'CONTRACT_FAILURE' AND code = "
            "'CONTRACT_PROCESSING_ERROR')"
            ")",
            name="class_code_consistent",
        ),
    )
