"""Behavioral rule models for the CORRECT pillar.

Six rule types that persist across sessions and enforce
durable behavioral constraints on tool usage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Rule kinds
# ---------------------------------------------------------------------------


class RuleKind(StrEnum):
    PREREQUISITE = "prerequisite"
    PROHIBITION = "prohibition"
    PARAMETER = "parameter"
    SEQUENCE = "sequence"
    RATE = "rate"
    APPROVAL = "approval"


class RuleStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# Per-kind config models
# ---------------------------------------------------------------------------


class PrerequisiteConfig(BaseModel):
    """Tool X must be called before tool Y."""

    required_tool_ids: list[str]
    required_args: dict[str, Any] = Field(default_factory=dict)


class ProhibitionConfig(BaseModel):
    """Prohibit tool usage unconditionally or after certain events."""

    after_tool_ids: list[str] = Field(default_factory=list)
    always: bool = False


class ParameterConfig(BaseModel):
    """Constrain parameter values by whitelist, blacklist, range, or regex."""

    param_name: str
    allowed_values: list[Any] | None = None
    blocked_values: list[Any] | None = None
    max_value: float | None = None
    min_value: float | None = None
    pattern: str | None = None


class SequenceConfig(BaseModel):
    """Enforce a required call order."""

    required_order: list[str]


class SessionRateConfig(BaseModel):
    """Limit call frequency within a session or time window."""

    max_calls: int
    window_seconds: int | None = None
    per_tool: bool = True


class ApprovalConfig(BaseModel):
    """Require explicit approval under certain conditions."""

    when_param_matches: dict[str, Any] = Field(default_factory=dict)
    when_after_tool: str | None = None
    approval_message: str = "Approval required."


# Union of all config types for discriminated parsing
RuleConfig = (
    PrerequisiteConfig
    | ProhibitionConfig
    | ParameterConfig
    | SequenceConfig
    | SessionRateConfig
    | ApprovalConfig
)

# Map kind -> config class for deserialization
_KIND_TO_CONFIG: dict[RuleKind, type[BaseModel]] = {
    RuleKind.PREREQUISITE: PrerequisiteConfig,
    RuleKind.PROHIBITION: ProhibitionConfig,
    RuleKind.PARAMETER: ParameterConfig,
    RuleKind.SEQUENCE: SequenceConfig,
    RuleKind.RATE: SessionRateConfig,
    RuleKind.APPROVAL: ApprovalConfig,
}


# ---------------------------------------------------------------------------
# Core rule model
# ---------------------------------------------------------------------------


class BehavioralRule(BaseModel):
    """A single behavioral rule that constrains tool usage."""

    rule_id: str
    kind: RuleKind
    description: str
    status: RuleStatus = RuleStatus.ACTIVE
    priority: int = 100
    target_tool_ids: list[str] = Field(default_factory=list)
    target_methods: list[str] = Field(default_factory=list)
    target_hosts: list[str] = Field(default_factory=list)
    config: RuleConfig
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"

    @model_validator(mode="before")
    @classmethod
    def _migrate_enabled_to_status(cls, data: Any) -> Any:
        """Legacy migration: convert enabled bool to status."""
        if isinstance(data, dict) and "enabled" in data:
            enabled = data.pop("enabled")
            if "status" not in data:
                data["status"] = RuleStatus.ACTIVE if enabled else RuleStatus.DISABLED
        return data

    def model_post_init(self, __context: Any) -> None:
        """Ensure config type matches kind on deserialization."""
        if isinstance(self.config, dict):
            expected_cls = _KIND_TO_CONFIG.get(self.kind)
            if expected_cls:
                self.config = expected_cls.model_validate(self.config)


# ---------------------------------------------------------------------------
# Evaluation result models
# ---------------------------------------------------------------------------


class RuleViolation(BaseModel):
    """A single rule violation."""

    rule_id: str
    rule_kind: RuleKind
    tool_id: str
    description: str
    feedback: str
    suggestion: str | None = None
    severity: str = "error"


class RuleEvaluation(BaseModel):
    """Result of evaluating all applicable rules for a tool call."""

    allowed: bool
    violations: list[RuleViolation]
    feedback: str


class RuleConflict(BaseModel):
    """A detected conflict between two rules."""

    rule_a_id: str
    rule_b_id: str
    conflict_type: str
    description: str
