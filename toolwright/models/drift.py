"""Drift detection models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DriftType(StrEnum):
    """Classification of drift."""

    BREAKING = "breaking"  # Response schema change, removed endpoint
    AUTH = "auth"  # Auth mechanism changed
    RISK = "risk"  # New state-changing endpoint
    ADDITIVE = "additive"  # New read-only endpoint
    SCHEMA = "schema"  # Schema change (non-breaking)
    PARAMETER = "parameter"  # Parameter added/removed/changed
    CONTRACT = "contract"  # Verification contract assertion failed
    UNKNOWN = "unknown"  # Unclassified (default to block)


class DriftSeverity(StrEnum):
    """Severity of drift."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DriftItem(BaseModel):
    """A single detected drift."""

    id: str
    type: DriftType
    severity: DriftSeverity

    # What changed
    endpoint_id: str | None = None
    path: str | None = None
    method: str | None = None

    # Description
    title: str
    description: str

    # Before/after for comparison
    before: Any | None = None
    after: Any | None = None

    # Recommendation
    recommendation: str | None = None


class DriftReport(BaseModel):
    """Complete drift report."""

    # Metadata
    id: str
    schema_version: str = "1.0"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Comparison info
    from_capture_id: str | None = None
    to_capture_id: str | None = None
    from_baseline_id: str | None = None
    from_timestamp: datetime | None = None
    to_timestamp: datetime | None = None

    # Summary counts
    total_drifts: int = 0
    breaking_count: int = 0
    auth_count: int = 0
    risk_count: int = 0
    additive_count: int = 0
    schema_count: int = 0
    parameter_count: int = 0
    contract_count: int = 0
    unknown_count: int = 0

    # Drifts
    drifts: list[DriftItem] = Field(default_factory=list)

    # Overall assessment
    has_breaking_changes: bool = False
    requires_review: bool = False

    # Exit code for CI
    exit_code: int = 0  # 0 = ok, 1 = warnings, 2 = breaking
