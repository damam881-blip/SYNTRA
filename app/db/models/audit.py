"""Project deletion audit that survives the project purge.

Deleting a project removes its aggregate, revisions, snapshots, results and
project-scoped logs in one transaction.  That is intentional and confirmed by
name, but the deletion itself must remain auditable.  A tombstone row keeps the
project identity and the last committed revisions *after* the purge.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, positive_check, uuid7_check


class ProjectTombstone(Base):
    __tablename__ = "project_tombstone"

    project_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_name: Mapped[str] = mapped_column(String(64), nullable=False)
    last_state_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_simulation_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deleted_by: Mapped[str] = mapped_column(
        String(128), nullable=False, default="system"
    )
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        uuid7_check("project_id", "tombstone_id_uuid7"),
        positive_check("last_state_revision", "tombstone_state_revision_positive"),
        positive_check(
            "last_simulation_revision", "tombstone_simulation_revision_positive"
        ),
        CheckConstraint(
            "last_simulation_revision <= last_state_revision",
            name="tombstone_simulation_not_ahead",
        ),
        CheckConstraint(
            "length(btrim(project_name)) > 0", name="tombstone_name_not_blank"
        ),
    )
