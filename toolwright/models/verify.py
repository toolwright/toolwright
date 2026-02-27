"""Verification models for contract checking, replay, outcomes, and evidence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class VerifyMode(StrEnum):
    """Verification modes."""

    CONTRACTS = "contracts"
    REPLAY = "replay"
    OUTCOMES = "outcomes"
    PROVENANCE = "provenance"
    ALL = "all"


class VerifyStatus(StrEnum):
    """Status of a verification check."""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"


class AssertionOp(StrEnum):
    """Assertion comparison operators."""

    EQUALS = "equals"
    MATCHES_REGEX = "matches_regex"
    CONTAINS = "contains"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EXISTS = "exists"


class FlakePolicy(BaseModel):
    """Policy for handling flaky verification results."""

    max_retries: int = 2
    pass_threshold: float = 0.8
    backoff_ms: int = 500


class Assertion(BaseModel):
    """A single verification assertion."""

    type: Literal["api_state", "schema_check", "field_match"] = "field_match"
    endpoint_ref: str | None = None
    field_path: str
    op: AssertionOp = AssertionOp.EXISTS
    value: Any = None
    description: str = ""


class VerificationContract(BaseModel):
    """A verification contract defining expected post-conditions."""

    contract_id: str = Field(
        default_factory=lambda: f"vc_{uuid.uuid4().hex[:8]}"
    )
    toolpack_digest: str = ""
    targets: list[str] = Field(default_factory=list)
    assertions: list[Assertion] = Field(default_factory=list)
    risk_tier: str = "low"
    flake_policy: FlakePolicy = Field(default_factory=FlakePolicy)
    evidence_policy_ref: str | None = None


class AssertionResult(BaseModel):
    """Result of evaluating a single assertion."""

    assertion: Assertion
    status: VerifyStatus = VerifyStatus.UNKNOWN
    actual_value: Any = None
    message: str = ""
    evidence_ref: str | None = None


class ContractResult(BaseModel):
    """Result of verifying a single contract."""

    contract_id: str
    status: VerifyStatus = VerifyStatus.UNKNOWN
    assertion_results: list[AssertionResult] = Field(default_factory=list)
    pass_count: int = 0
    fail_count: int = 0
    unknown_count: int = 0


class ReplayCheckResult(BaseModel):
    """Result of a single replay check."""

    endpoint_ref: str
    check_type: str  # "status_2xx", "schema_match", "field_present"
    status: VerifyStatus = VerifyStatus.UNKNOWN
    expected: Any = None
    actual: Any = None
    message: str = ""


class ReplayResult(BaseModel):
    """Result of replay verification mode."""

    status: VerifyStatus = VerifyStatus.UNKNOWN
    baseline_path: str | None = None
    checks: list[ReplayCheckResult] = Field(default_factory=list)
    pass_count: int = 0
    fail_count: int = 0
    unknown_count: int = 0


class OutcomesResult(BaseModel):
    """Result of outcomes verification mode."""

    status: VerifyStatus = VerifyStatus.UNKNOWN
    contract_results: list[ContractResult] = Field(default_factory=list)
    pass_count: int = 0
    fail_count: int = 0
    unknown_count: int = 0


class EvidenceEntry(BaseModel):
    """A single entry in an evidence bundle."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    event_type: str  # "verify_result", "drift_detected", "decision_made"
    source: str  # "verify_engine", "drift_engine", "decision_engine"
    data: dict[str, Any] = Field(default_factory=dict)
    redaction_profile: str = "default_safe"
    digest: str = ""


class EvidenceBundle(BaseModel):
    """A collection of evidence entries with integrity digest."""

    bundle_id: str = Field(
        default_factory=lambda: f"ev_{datetime.now(UTC).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    toolpack_id: str = ""
    context: str = ""  # "verify", "drift", "runtime"
    entries: list[EvidenceEntry] = Field(default_factory=list)
    redaction_profile: str = "default_safe"
    bundle_digest: str = ""


class VerifyReport(BaseModel):
    """Complete verification report."""

    id: str = Field(
        default_factory=lambda: f"vr_{datetime.now(UTC).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
    )
    schema_version: str = "1.0"
    generated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    toolpack_id: str = ""
    mode: str = "all"
    governance_mode: str = "pre-approval"
    config: dict[str, Any] = Field(default_factory=dict)
    contracts: ContractResult | None = None
    replay: ReplayResult | None = None
    outcomes: OutcomesResult | None = None
    provenance: dict[str, Any] | None = None
    evidence_bundle_id: str | None = None
    tool_ids: list[str] = Field(default_factory=list)
    exit_code: int = 0
    overall_status: VerifyStatus = VerifyStatus.UNKNOWN
