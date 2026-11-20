"""Canonical exceptions for the TASK-06 persistence layer."""

from __future__ import annotations


class ProjectNotFoundError(LookupError):
    """No stored project matches the requested identifier."""


class DeletionConfirmationError(ValueError):
    """Deletion was refused because the confirmation string did not match."""


class PreconditionConflictError(ValueError):
    """The request conflicts with the committed project state (or is a no-op)."""


class IntegrityConflictError(ValueError):
    """A uniqueness/occupancy rule was violated before the database commit."""


class ContractValidationError(ValueError):
    """A contract document does not satisfy the approved schema invariants."""
