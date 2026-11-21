"""TASK-06 project-scoped action, Ping and error logs plus retention policy."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, positive_check, uuid7_check
from app.db.enums import AggregateOutcome, ErrorClass, ErrorReason, ExecutionStatus
from app.db.pgtypes import AGGREGATE_OUTCOME, ERROR_CLASS, ERROR_REASON, EXECUTION_STATUS


class ActionLog(Base):
    __tablename__ = "action_log"

    log_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    action_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[uuid.UUID | None] = mapped_column()
    revision: Mapped[int | None] = mapped_column()
    detail_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        uuid7_check("log_id", "action_log_id_uuid7"),
        CheckConstraint("length(action_kind) > 0", name="action_kind_not_empty"),
        ForeignKeyConstraint(
            ["project_id", "revision"],
            ["project_revision.project_id", "project_revision.revision"],
            ondelete="CASCADE",
            name="fk_action_log_revision",
        ),
    )


class PingLog(Base):
    __tablename__ = "ping_log"

    log_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    aggregate_outcome: Mapped[AggregateOutcome | None] = mapped_column(
        AGGREGATE_OUTCOME, nullable=True
    )
    execution_status: Mapped[ExecutionStatus] = mapped_column(EXECUTION_STATUS, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        uuid7_check("log_id", "ping_log_id_uuid7"),
        UniqueConstraint("project_id", "test_id", name="uq_ping_log_project_test"),
        ForeignKeyConstraint(
            ["project_id", "test_id"],
            ["ping_test_command.project_id", "ping_test_command.test_id"],
            ondelete="CASCADE",
            name="fk_ping_log_command",
        ),
        ForeignKeyConstraint(
            ["project_id", "snapshot_id"],
            ["snapshot_ref.project_id", "snapshot_ref.snapshot_id"],
            ondelete="CASCADE",
            name="fk_ping_log_snapshot",
        ),
    )


class ErrorLog(Base):
    __tablename__ = "error_log"

    log_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"), index=True
    )
    error_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("error_envelope.error_id", ondelete="CASCADE"), nullable=False
    )
    error_class: Mapped[ErrorClass] = mapped_column(ERROR_CLASS, nullable=False)
    code: Mapped[ErrorReason] = mapped_column(ERROR_REASON, nullable=False)
    message_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (uuid7_check("log_id", "error_log_id_uuid7"),)


class RetentionPolicy(Base):
    __tablename__ = "retention_policy"

    policy_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    action_log_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    ping_log_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    error_log_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    ping_result_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    snapshot_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("policy_name <> ''", name="policy_name_not_empty"),
        positive_check("action_log_retention_days", "action_retention_positive"),
        positive_check("ping_log_retention_days", "ping_retention_positive"),
        positive_check("error_log_retention_days", "error_retention_positive"),
        positive_check("ping_result_retention_days", "result_retention_positive"),
        positive_check("snapshot_retention_days", "snapshot_retention_positive"),
    )
