"""Repair diagnosis, patch, and report models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from toolwright.models.decision import ReasonCode
from toolwright.models.drift import DriftSeverity, DriftType
from toolwright.models.verify import VerifyStatus


class DiagnosisSource(StrEnum):
    """Where the diagnosis evidence came from."""

    AUDIT_LOG = "audit_log"
    DRIFT_REPORT = "drift_report"
    VERIFY_REPORT = "verify_report"


class DiagnosisItem(BaseModel):
    """A single diagnosed issue."""

    id: str  # deterministic SHA-256 hash of key fields
    source: DiagnosisSource
    severity: DriftSeverity

    # Source-specific linkage (exactly one is populated)
    reason_code: ReasonCode | None = None  # audit-sourced
    drift_type: DriftType | None = None  # drift-sourced
    verify_status: VerifyStatus | None = None  # verify-sourced

    # Context
    tool_id: str | None = None
    host: str | None = None
    path: str | None = None
    method: str | None = None

    # Human-readable
    title: str
    description: str

    # Grouping
    cluster_key: str  # e.g. "tool:get_users", "reason:denied_policy"

    # Raw evidence (redacted before output)
    raw_evidence: dict[str, Any] = Field(default_factory=dict)


class PatchKind(StrEnum):
    """Safety classification of a proposed patch.

    SAFE: read-only or regeneration with zero capability expansion.
    APPROVAL_REQUIRED: changes approved state or grants new capability.
    MANUAL: requires capture, auth work, code changes, or investigation.
    """

    SAFE = "safe"
    APPROVAL_REQUIRED = "approval_required"
    MANUAL = "manual"


class PatchAction(StrEnum):
    """Machine-readable intent for a proposed patch."""

    GATE_ALLOW = "gate_allow"
    GATE_SYNC = "gate_sync"
    GATE_RESEAL = "gate_reseal"
    VERIFY_CONTRACTS = "verify_contracts"
    VERIFY_PROVENANCE = "verify_provenance"
    INVESTIGATE = "investigate"
    RE_MINT = "re_mint"
    REVIEW_POLICY = "review_policy"
    ADD_HOST = "add_host"


class PatchItem(BaseModel):
    """A single proposed fix."""

    id: str
    diagnosis_id: str  # links back to DiagnosisItem.id
    kind: PatchKind
    action: PatchAction
    args: dict[str, Any] = Field(default_factory=dict)  # structured intent
    cli_command: str  # exact copy-pasteable command
    title: str
    description: str
    reason: str  # why this fixes the diagnosis
    risk_note: str | None = None  # e.g. "expands host allowlist"


class RedactionSummary(BaseModel):
    """Summary of redaction applied to evidence."""

    redacted_field_count: int = 0
    redacted_keys: list[str] = Field(default_factory=list)


class VerifySnapshot(BaseModel):
    """Pre-apply verification snapshot (contracts mode only)."""

    verify_status: VerifyStatus
    summary: dict[str, Any] = Field(default_factory=dict)


class RepairDiagnosis(BaseModel):
    """Aggregated diagnosis output."""

    total_issues: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)
    clusters: dict[str, list[str]] = Field(
        default_factory=dict
    )  # cluster_key -> diagnosis IDs
    context_files_used: list[str] = Field(default_factory=list)
    items: list[DiagnosisItem] = Field(default_factory=list)


class RepairPatchPlan(BaseModel):
    """Aggregated patch plan."""

    total_patches: int = 0
    safe_count: int = 0
    approval_required_count: int = 0
    manual_count: int = 0
    patches: list[PatchItem] = Field(default_factory=list)
    commands_sh: str = ""  # all commands concatenated for copy-paste


class RepairReport(BaseModel):
    """Top-level repair report."""

    repair_schema_version: str = "0.1"
    generated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    toolpack_id: str
    toolpack_path: str
    diagnosis: RepairDiagnosis
    patch_plan: RepairPatchPlan
    verify_before: VerifySnapshot | None = None
    redaction_summary: RedactionSummary = Field(default_factory=RedactionSummary)
    exit_code: int = 0  # 0=healthy, 1=report generated, 2=CLI error
