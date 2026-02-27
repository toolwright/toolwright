"""Policy models for enforcement."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RuleType(StrEnum):
    """Types of policy rules."""

    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"
    REDACT = "redact"
    BUDGET = "budget"
    AUDIT = "audit"


class MatchCondition(BaseModel):
    """Condition for matching requests."""

    # Host matching
    hosts: list[str] | None = None
    host_pattern: str | None = None  # Regex

    # Path matching
    paths: list[str] | None = None
    path_pattern: str | None = None  # Regex

    # Method matching
    methods: list[str] | None = None

    # Header matching
    headers: dict[str, str] | None = None

    # Risk tier matching
    risk_tiers: list[str] | None = None

    # Scope matching
    scopes: list[str] | None = None

    def matches(
        self,
        method: str,
        path: str,
        host: str,
        headers: dict[str, str] | None = None,
        risk_tier: str | None = None,
        scope: str | None = None,
    ) -> bool:
        """Check if this condition matches the given request.

        Args:
            method: HTTP method
            path: Request path
            host: Request host
            headers: Request headers
            risk_tier: Risk tier of the endpoint
            scope: Scope name

        Returns:
            True if all conditions match
        """
        # Method matching
        if self.methods is not None and method.upper() not in [m.upper() for m in self.methods]:
            return False

        # Host matching
        if self.hosts is not None and host.lower() not in [h.lower() for h in self.hosts]:
            return False

        if self.host_pattern is not None and not re.match(self.host_pattern, host, re.IGNORECASE):
            return False

        # Path matching
        if self.paths is not None and path not in self.paths:
            return False

        if self.path_pattern is not None and not re.match(self.path_pattern, path, re.IGNORECASE):
            return False

        # Header matching
        if self.headers is not None and headers is not None:
            for key, value in self.headers.items():
                if key.lower() not in {k.lower(): v for k, v in headers.items()}:
                    return False
                if headers.get(key, "").lower() != value.lower():
                    return False

        # Risk tier matching
        if self.risk_tiers is not None and risk_tier is not None and risk_tier not in self.risk_tiers:
            return False

        # Scope matching
        if self.scopes is not None:
            if scope is None:
                return False
            return scope in self.scopes

        return True


class PolicyRule(BaseModel):
    """A single policy rule."""

    id: str
    name: str
    description: str | None = None

    # Rule type
    type: RuleType

    # When this rule applies
    match: MatchCondition

    # Priority (higher = evaluated first)
    priority: int = 0

    # Rule-specific settings
    settings: dict[str, Any] = Field(default_factory=dict)
    # For BUDGET: {"per_minute": 10, "per_hour": 100}
    # For REDACT: {"fields": ["authorization", "cookie"]}
    # For CONFIRM: {"message": "This will delete data. Proceed?"}


class StateChangingOverride(BaseModel):
    """Explicit state-changing override for a tool or endpoint selector."""

    tool_id: str | None = None
    method: str | None = None
    path: str | None = None
    host: str | None = None
    state_changing: bool
    justification: str | None = None


class Policy(BaseModel):
    """Complete policy configuration."""

    # Metadata
    version: str = "1.0.0"
    schema_version: str = "1.0"
    name: str
    description: str | None = None

    # Default behavior (deny by default for safety)
    default_action: RuleType = RuleType.DENY

    # Rules (evaluated in priority order)
    rules: list[PolicyRule] = Field(default_factory=list)

    # Global settings
    global_rate_limit: int | None = None
    audit_all: bool = True

    # Redaction defaults
    redact_headers: list[str] = Field(
        default_factory=lambda: [
            "authorization",
            "cookie",
            "set-cookie",
            "x-api-key",
        ]
    )
    redact_patterns: list[str] = Field(
        default_factory=lambda: [
            r"bearer\s+[a-zA-Z0-9\-_.]+",
            r"api[_-]?key[=:]\s*[a-zA-Z0-9]+",
        ]
    )

    # Scope this policy applies to
    scope: str | None = None
    state_changing_overrides: list[StateChangingOverride] = Field(default_factory=list)

    def get_rules_by_priority(self) -> list[PolicyRule]:
        """Get rules sorted by priority (highest first)."""
        return sorted(self.rules, key=lambda r: r.priority, reverse=True)


class EvaluationResult(BaseModel):
    """Result of policy evaluation."""

    # Decision
    allowed: bool
    rule_id: str | None = None
    rule_type: RuleType | None = None

    # Action details
    requires_confirmation: bool = False
    confirmation_message: str | None = None

    # Budget info
    budget_exceeded: bool = False
    budget_remaining: int | None = None

    # Audit info
    should_audit: bool = True
    audit_level: str = "standard"

    # Redaction
    redact_fields: list[str] = Field(default_factory=list)

    # Reason for decision
    reason: str = ""
