"""Data models for the auto-healing system.

Defines the canonical types for response samples, inferred schemas,
drift diagnosis, validation, and confidence scoring. These models
power the heal pipeline: capture → infer → detect → diagnose → validate → deploy.

All 15 change types map to 5 severity levels. The severity() method
on ChangeType is the single source of truth for this mapping.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

# ── Enums ──────────────────────────────────────────────────────────


class FieldType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    NULL = "null"
    UNKNOWN = "unknown"


class PresenceConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class HealDriftSeverity(StrEnum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_CHANGE_SEVERITY: dict[str, HealDriftSeverity] = {
    "field_added": HealDriftSeverity.SAFE,
    "optionality_changed": HealDriftSeverity.SAFE,
    "header_changed": HealDriftSeverity.SAFE,
    "rate_limit_changed": HealDriftSeverity.SAFE,
    "field_renamed": HealDriftSeverity.LOW,
    "nullability_changed": HealDriftSeverity.LOW,
    "status_code_changed": HealDriftSeverity.LOW,
    "field_removed": HealDriftSeverity.MEDIUM,
    "type_changed": HealDriftSeverity.MEDIUM,
    "value_format_changed": HealDriftSeverity.MEDIUM,
    "endpoint_moved": HealDriftSeverity.MEDIUM,
    "structure_changed": HealDriftSeverity.HIGH,
    "nesting_changed": HealDriftSeverity.HIGH,
    "pagination_changed": HealDriftSeverity.HIGH,
    "auth_changed": HealDriftSeverity.CRITICAL,
}


class ChangeType(StrEnum):
    FIELD_ADDED = "field_added"
    FIELD_REMOVED = "field_removed"
    FIELD_RENAMED = "field_renamed"
    TYPE_CHANGED = "type_changed"
    NULLABILITY_CHANGED = "nullability_changed"
    OPTIONALITY_CHANGED = "optionality_changed"
    STRUCTURE_CHANGED = "structure_changed"
    NESTING_CHANGED = "nesting_changed"
    VALUE_FORMAT_CHANGED = "value_format_changed"
    ENDPOINT_MOVED = "endpoint_moved"
    STATUS_CODE_CHANGED = "status_code_changed"
    HEADER_CHANGED = "header_changed"
    PAGINATION_CHANGED = "pagination_changed"
    AUTH_CHANGED = "auth_changed"
    RATE_LIMIT_CHANGED = "rate_limit_changed"

    def severity(self) -> HealDriftSeverity:
        return _CHANGE_SEVERITY[self.value]


# ── Value types ────────────────────────────────────────────────────


class FieldTypeInfo(BaseModel):
    """Single entry in a typed_shape dict. Maps a dotted path to its types."""

    types: list[str]
    nullable: bool = False


class FieldSchema(BaseModel):
    """Schema for a single field in an inferred schema."""

    name: str
    path: str
    field_type: str
    nullable: bool = False
    optional: bool = False
    presence_rate: float = 1.0
    presence_confidence: str = "low"
    observed_types: list[str] = []
    example_values: list[str] = []


class InferredSchema(BaseModel):
    """Inferred schema for a tool variant, aggregated from response samples."""

    tool_id: str
    variant: str
    schema_hash: str
    sample_count: int
    first_seen: float
    last_seen: float
    response_type: str
    fields: dict[str, FieldSchema]


class ResponseSample(BaseModel):
    """Stored observation of a single API response."""

    tool_id: str
    variant: str
    timestamp: float
    status_code: int
    latency_ms: int
    schema_hash: str
    typed_shape: dict[str, FieldTypeInfo]
    presence_paths: list[str]
    examples: dict[str, str]


# ── Drift diagnosis ────────────────────────────────────────────────


class DriftChange(BaseModel):
    """A single classified change between baseline and current schema."""

    change_type: ChangeType
    severity: HealDriftSeverity
    field_path: str
    description: str
    old_value: str | None = None
    new_value: str | None = None
    needs_code_repair: bool = False
    repair_hint: str | None = None


class DriftDiagnosis(BaseModel):
    """Complete drift diagnosis for a tool variant."""

    tool_id: str
    variant: str
    tool_source_path: str
    timestamp: float
    overall_severity: HealDriftSeverity
    needs_code_repair: bool
    source_available: bool
    baseline_schema_hash: str
    current_schema_hash: str
    changes: list[DriftChange]
    baseline_sample: dict[str, Any] = {}
    current_sample: dict[str, Any] = {}

    def format_for_agent(self) -> str:
        """Format diagnosis as agent-readable text."""
        lines = [
            f"Drift Diagnosis: {self.tool_id} ({self.variant})",
            f"Severity: {self.overall_severity.value.upper()}",
            f"Source: {self.tool_source_path}",
            f"Needs code repair: {self.needs_code_repair}",
            "",
            "Changes:",
        ]
        for c in self.changes:
            lines.append(f"  - [{c.severity.value.upper()}] {c.change_type.value}: {c.field_path}")
            lines.append(f"    {c.description}")
            if c.old_value:
                lines.append(f"    Old: {c.old_value}")
            if c.new_value:
                lines.append(f"    New: {c.new_value}")
            if c.repair_hint:
                lines.append(f"    Hint: {c.repair_hint}")
        if self.baseline_sample:
            lines.append("")
            lines.append(f"Baseline sample: {json.dumps(self.baseline_sample)}")
        if self.current_sample:
            lines.append(f"Current sample: {json.dumps(self.current_sample)}")
        return "\n".join(lines)

    def format_compact(self) -> str:
        """Single-line summary."""
        change_summary = ", ".join(
            f"{c.change_type.value}@{c.field_path}" for c in self.changes
        )
        return (
            f"{self.tool_id}({self.variant}) "
            f"severity={self.overall_severity.value} "
            f"changes=[{change_summary}]"
        )

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, data: str) -> DriftDiagnosis:
        return cls.model_validate_json(data)


# ── Validation ─────────────────────────────────────────────────────


class ValidationCheck(BaseModel):
    """Single validation check result."""

    name: str
    passed: bool
    detail: str


class ValidationResult(BaseModel):
    """Aggregate validation result."""

    passed: bool
    checks: list[ValidationCheck] = []
    error: str | None = None


# ── Confidence + cost ──────────────────────────────────────────────


class ConfidenceScore(BaseModel):
    """Weighted confidence score for a repair."""

    value: float
    factors: dict[str, float] = {}


class RepairCostEntry(BaseModel):
    """Cost tracking for a single repair operation."""

    tool_id: str
    mode: str
    tokens_used: int
    cost_usd: float
    timestamp: float
